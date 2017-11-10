from flask import Flask, redirect, render_template, url_for, flash, request
import boto3
from datetime import datetime, timedelta
import pymysql
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


def monitor():
    # checks every fifteen seconds if resizing is needed
        # extract the parameters from the db
        cur.execute("SELECT * FROM auto_scale")
        row = cur.fetchone()
        if row:
            upper_threshold = row[0]
            lower_threshold = row[1]
            grow_ratio = row[2]
            shrink_ratio = row[3]
        else:
            print("No data in the auto_scale table.\n")
        print("In monitor")
        # resize pool based on the current thresholds
        instance_num = resize_pool(upper_threshold, lower_threshold)
        print(instance_num)
        # determine how many new instances need to be added or subtracted
        add_instance_num = grow_ratio * instance_num - instance_num
        subtract_instance_num = instance_num - instance_num / shrink_ratio
        delta_instance_num = abs(add_instance_num - subtract_instance_num)

        # create or terminate the instances and resize the pool
        if add_instance_num > subtract_instance_num:
            for i in range(int(delta_instance_num)):
                create_instance()
        elif add_instance_num < subtract_instance_num:
            for i in range(int(delta_instance_num)):
                terminate_instance()
        instance_num = resize_pool(upper_threshold, lower_threshold)
        print(instance_num)
        if instance_num:
            flash("Worker pool resize based on threshold.")
        # reset the growing and shrinking ratios in the db
        set_auto_scale(upper_threshold, lower_threshold, 1, 1)

sched = BackgroundScheduler(daemon=True)
#sched.add_job(monitor, 'interval', seconds=10)
#sched.start()

db = pymysql.connect("172.31.82.239", "ece1779", "secret", "ece1779")
# initializes app and connect to db
app = Flask(__name__)
cur = db.cursor()
app.config.from_pyfile('config.cfg')
# connect to ec2, s3, elb using boto3
s3 = boto3.resource('s3', region_name='us-east-1', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                    aws_secret_access_key='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')
ec2 = boto3.resource('ec2', region_name='us-east-1', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                    aws_secret_access_key='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')
lb = boto3.client('elb', region_name='us-east-1', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                    aws_secret_access_key='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')
cloud = boto3.client('cloudwatch', region_name='us-east-1', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                     aws_secret_access_key='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')


@app.route('/')
# Returns the dashboard page which displays all 4 managerUI functionality
def index():
    re = get_cloud_metric()
    return render_template('dashboard.html', workers=re)


@app.route('/change', methods=['POST'])
# POST method that grows and shrinks worker pool by 1
def change():
    if request.method == 'POST':
        checked = request.form['modify_pool']
        if checked == 'up':
            create_instance()
            flash('New worker created.')
        elif checked == 'down':
            if terminate_instance():
                flash('Worker terminated！')
            else:
                flash('No more workers to terminate！')
    return redirect(url_for('index'))


@app.route('/scale', methods=['POST'])
# POST method that inserts the auto-scaling policy parameters into the db
def scale():
    if request.method == 'POST':
        cur.execute("SELECT * FROM auto_scale")
        row = cur.fetchone()
        if row:
            upper_thresh = row[0]
            lower_thresh = row[1]
            grow_db = row[2]
            shrink_db = row[3]
        grow_cpu = request.form.get("grow_cpu")
        shrink_cpu = request.form.get("shrink_cpu")
        grow = request.form.get("grow_ratio")
        shrink = request.form.get("shrink_ratio")
        if grow_cpu:
            upper_thresh = grow_cpu
        if shrink_cpu:
            lower_thresh = shrink_cpu
        if grow:
            grow_db = grow
        if shrink:
            shrink_db = shrink
        if float(upper_thresh) < float(lower_thresh):
            flash("Shrinking threshold cannot be higher than growing threshold.")
            return redirect(url_for('index'))

        set_auto_scale(upper_thresh, lower_thresh, grow_db, shrink_db)
        flash("The parameters have been set!")
    return redirect(url_for('index'))


@app.route('/delete', methods=['POST'])
# deleting data from the database and s3
def delete():
    cur.execute("DELETE FROM Users")
    cur.execute("DELETE FROM Img")
    set_auto_scale(100, 0, 1, 1)
    db.commit()
    bucket = s3.Bucket('ece1779xdz')
    bucket.objects.all().delete()
    flash("All data has been removed.")
    return redirect(url_for('index'))


def calculate_total_cpu():
    """
    Calculate the total CPU utilization for all workers. 
    :return: [integer, integer] for total CPU and number of running instances.
    """
    re = get_cloud_metric()
    inst_num = len(re)
    cpu_sum = sum(re['cpu']) / max(inst_num, 1)
    print([cpu_sum, inst_num])
    return [cpu_sum, inst_num]


def create_instance():
    """
    Grow the worker pool by creating a new instance.
    :return: Null 
    """
    user_data_script = """#!/bin/bash\n
    cd home/ubuntu/Desktop/ece1779/\n
    source aws/venv/bin/activate\n
    cd a2/userUI/\n
    ./run.sh
    """
    instance = ec2.create_instances(
        ImageId='ami-9c6dd3e6',
        InstanceType='t2.micro',
        KeyName='ece1779',
        MaxCount=1,
        MinCount=1,
        Monitoring={'Enabled': True},
        SecurityGroupIds=['sg-751f1e06'],
        UserData=user_data_script
    )
    lb.register_instances_with_load_balancer(
        LoadBalancerName='ece1779lb',
        Instances=[{'InstanceId': instance[0].id}]
    )
    ec2.create_tags(Resources=[instance[0].id], Tags=[{'Key': 'Name', 'Value': 'userUI'}])


def terminate_instance():
    """
    Shrink the worker pool by terminating a new instance.
    :return: Bool
    """
    inst_id = 0
    instances = get_instances()
    for instance in instances:
        inst_id = instance.id
    if inst_id != 0:
        lb.deregister_instances_from_load_balancer(
            LoadBalancerName='ece1779lb',
            Instances=[{'InstanceId': inst_id}])
        ec2.instances.filter(InstanceIds=[inst_id]).terminate()
        return True
    return False


def resize_pool(upper_threshold, lower_threshold):
    """
    Resize the worker pool by calculating the CPU utilization and checks if it meets the upper and lower 
    threshold. 
    :param upper_threshold: float 
    :param lower_threshold: float
    :return: int the number of running instances
    """
    cpu_sum, inst_num = calculate_total_cpu()
    while cpu_sum > upper_threshold:
        terminate_instance()
        cpu_sum, inst_num = calculate_total_cpu()

    while cpu_sum < lower_threshold:
        create_instance()
        cpu_sum, inst_num = calculate_total_cpu()
    return inst_num


def set_auto_scale(upper, lower, grow, shrink):
    """
    Sets the auto scaling parameters and insert them in the db.
    :param upper: float 
    :param lower: float
    :param grow: int
    :param shrink: int
    :return: null
    """
    query = '''UPDATE auto_scale
                   SET upper = %s,
                       lower = %s,
                       grow = %s,
                       shrink = %s
            WHERE id = "1"
    '''
    cur.execute(query, (upper, lower, grow, shrink))
    db.commit()


def get_instances():
    return ec2.instances.filter(
        Filters=[{'Name': 'tag-value', 'Values': ['userUI']},
                 {'Name': 'instance-state-name', 'Values': ['running', 'pending']}])


def get_cloud_metric():
    instances = get_instances()
    re = []
    for instance in instances:
        sum = 0
        num = 0
        cpu = cloud.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance.id}],
            Period=60,
            StartTime=datetime.utcnow() - timedelta(seconds=120),
            EndTime=datetime.utcnow(),
            Statistics=['Average']
        )
        if cpu['Datapoints']:
            for data_point in cpu['Datapoints']:
                sum += data_point['Average']
                num += 1
            inst = {
                    'name': instance.id,
                    'cpu': sum/num
                }
            re.append(inst)
        else:
            inst = {
                    'name': instance.id,
                    'cpu': "Collecting data."
                }
            re.append(inst)
    return re

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

