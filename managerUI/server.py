from flask import Flask, redirect, render_template, url_for, flash, request
import boto3
from datetime import datetime, timedelta
import time
from flask_mysqldb import MySQL

# initializes app and connect to db
app = Flask(__name__)
mysql = MySQL(app)
app.config.from_pyfile('config.cfg')
cur = mysql.connection.cursor()

# connect to ec2, s3, elb using boto3
s3 = boto3.resource('s3')
ec2 = boto3.resource('ec2')
lb = boto3.client('elb')


@app.route('/')
# Returns the dashboard page which displays all 4 managerUI functionality
def index():
    re = []
    instances = ec2.instances.all()
    cloud = boto3.client('cloudwatch')
    for instance in instances:
        print(instance.id, instance.instance_type)
        cpu = cloud.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            dimensions={'InstanceId': [instance.id]},
            Period=300,
            StartTime=datetime.utcnow() - timedelta(seconds=300),
            EndTime=datetime.utcnow(),
            Statistics='Average'
        )
        for data_point in cpu['Datapoints']:
            inst = {
                'name': instance.id,
                'cpu': data_point['Average']
            }
            re.append(inst)
    return render_template('dashboard.html', worker=re)


@app.route('/change')
# POST method that grows and shrinks worker pool by 1
def change():
    if request.method == 'POST':
        checked = request.form('option')
        if checked == 'up':
            create_instance()
            flash('New worker created！')
        elif checked == 'down':
            terminate_instance()
            flash('Worker terminated！')
    return redirect(url_for('index'))


@app.route('/scale')
# POST method that inserts the auto-scaling policy parameters into the db
def scale():
    if request.method == 'POST':
        grow_cpu = request.form.get("grow_cpu")
        shrink_cpu = request.form.get("shrink_cpu")
        grow = request.form.get("grow_ratio")
        shrink = request.form.get("shrink_ratio")
        set_auto_scale(grow_cpu, shrink_cpu, grow, shrink)
    return redirect(url_for('index'))


@app.route('/delete')
# deleting data from the database and s3
def delete():
    cur.execute("DELETE FROM Users")
    mysql.connection.commit()
    bucket = s3.Bucket('ece1779xdz')
    bucket.objects.all().delete()
    return redirect(url_for('index'))


def calculate_total_cpu():
    """
    Calculate the total CPU utilization for all workers. 
    :return: [integer, integer] for total CPU and number of running instances.
    """
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    inst_num = 0
    cpu_sum = 0
    for instance in instances:
        cpu = client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            dimensions={'InstanceId': [instance.id]},
            Period=300,
            StartTime=datetime.utcnow() - timedelta(seconds=300),
            EndTime=datetime.utcnow(),
            Statistics='Average'
        )
        for data_point in cpu['Datapoints']:
            cpu_sum += data_point['Average']
        inst_num += 1
    return [cpu_sum, inst_num]


def create_instance():
    """
    Grow the worker pool by creating a new instance.
    :return: Null 
    """
    instance = ec2.create_instances(
        ImageId='ami-e3f432f5',
        InstanceType='t2.micro',
        KeyName='ece1779',
        MaxCount=1,
        MinCount=1,
        Monitoring={'Enabled': True},
        SecurityGroupIds=['sg-751f1e06'],
        DryRun=True
    )
    lb.register_instances_with_load_balancer(
        LoadBalancerName='ece1779lb',
        Instances=[{'InstanceId': instance[0].id}]
    )


def terminate_instance():
    """
    Shrink the worker pool by terminating a new instance.
    :return: Null
    """
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    inst_id = instances[0].id
    lb.deregister_instances_from_load_balancer(
        LoadBalancerName='ece1779lb',
        Instances=[{'InstanceId': inst_id}])
    ec2.instances.filter(InstanceIds=[inst_id]).terminate()


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
    '''
    cur.execute(query, (upper, lower, grow, shrink))
    mysql.connection.commit()

if __name__ == "__main__":
    app.run()

# checks every fifteen seconds if resizing is needed
while True:
    time.sleep(15)
    client = boto3.client('cloudwatch')

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
        continue

    # resize pool based on the current thresholds
    instance_num = resize_pool(upper_threshold, lower_threshold)

    # determine how many new instances need to be added or subtracted
    add_instance_num = grow_ratio * instance_num - instance_num
    subtract_instance_num = instance_num - instance_num / shrink_ratio
    delta_instance_num = abs(add_instance_num - subtract_instance_num)

    # create or terminate the instances and resize the pool
    if add_instance_num > subtract_instance_num:
        for i in range(delta_instance_num):
            create_instance()
    elif add_instance_num < subtract_instance_num:
        for i in range(delta_instance_num):
            terminate_instance()
    resize_pool(upper_threshold, lower_threshold)

    # reset the growing and shrinking ratios in the db
    set_auto_scale(upper_threshold, lower_threshold, 1, 1)
