import os
from flask import Flask, request, flash, redirect, render_template, url_for, abort
from urllib.parse import urlparse, urljoin
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from passlib.hash import pbkdf2_sha256
import database
from werkzeug.utils import secure_filename
from wand.image import Image
from flask_thumbnails_wand import Thumbnail
import boto3

# initialize the app, thumbnail, db and s3
app = Flask(__name__)
app.config.from_pyfile('config.cfg')
database.init_db(app)
db = database.db
thumb = Thumbnail(app)
s3 = boto3.resource('s3', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                    aws_secret_access_key='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')
client = boto3.client('s3', aws_access_key_id='AKIAIDMH5U4PYNAACSKA',
                      aws_secret_access_key='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')

# set login manager parameters
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = u"Please login to access this page."
from model import Users, Img
from forms import RegistrationForm, LoginForm


@app.route('/')
def index():
    """ If the current user is authenticated, directly route to dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Validates the login parameters by checking the db and the pre-set validators."""
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        next_var = request.args.get('next')
        # is_safe_url should check if the url is safe for redirects.
        if not is_safe_url(next_var):
            return abort(400)
        user = Users.query.get(form.email.data)
        if user:
            # sets the authenticated parameter which is needed for sessions to recognize the user
            user.authenticated = True
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
        return redirect(next_var or url_for('home'))
    return render_template('login.html', form=form, email=request.cookies.get('email'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registers the user and sets a hashed password."""
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        hash_var = pbkdf2_sha256.encrypt(form.password.data, rounds=200000, salt_size=16)
        user = Users(form.email.data, hash_var)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash('User Registered！')
        return redirect(url_for('home'))
    return render_template('register.html', form=form)


@app.route("/logout", methods=["GET"])
@login_required
def logout():
    """Logout the current user."""
    user = current_user
    user.authenticated = False
    db.session.add(user)
    db.session.commit()
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def home():
    """Displays the user's images."""
    img = Img.query.filter_by(user_email=current_user.email)
    filename = []
    if img:
        for field in img:
            inputs = [field.img_name, field.img_trans1, field.img_trans2, field.img_trans3]
            filename.append(inputs)
    return render_template('dashboard.html', filename=filename)


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Upload function."""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return render_template("upload.html")
        file = request.files['file']
        result = upload_files(file, current_user)
        if not result:
            flash("File not uploaded.")
    return render_template("upload.html")


@app.route('/test/FileUpload', methods=['GET', 'POST'])
def test():
    """Bulk upload function."""
    if request.method == 'POST':
        user = Users.query.get(request.form['userID'])
        if user:
            if 'uploadedfile' not in request.files:
                flash('No file part')
                return render_template("fileUpload.html")
            file = request.files['uploadedfile']
            upload_files(file, user)
    return render_template("fileUpload.html")


def upload_files(file, cur_user):
    """
    Transform and upload the files on s3 and save the filename in the database

    :param req_file: request.files
    :param cur_user: session
    :return: [Bool, String} | Bool
    """
    # check if the post request has the file part
    # if user does not select file, browser also submit a empty part without filename
    if file.filename == '':
        flash('No selected file')
        return False
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        f_name = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # save the file on s3
        file.save(f_name)
        s3.meta.client.upload_file(f_name, 'ece1779xdz', filename)

        # returns an array of all the names after transformation
        f_trans = transform(filename, f_name)
        # remove item from temp directory
        f = os.listdir(app.config['UPLOAD_FOLDER'])
        for file in f:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], file))

        # saves all the file names in the db
        img = Img(filename, cur_user.email, f_trans[0], f_trans[1], f_trans[2])
        image = Img.query.filter_by(img_name=filename, user_email=cur_user.email).first()
        if image is None:
            db.session.add(img)
            db.session.commit()
            flash('Photo Uploaded!')
            return True
        else:
            flash("This user has already uploaded a photo with the same filename. Please upload another"
                  "photo.")
    return False


def transform(filename, f_name):
    """
    Performs three transformations and save the transformed images on s3
    :param filename: String.
    :param f_name: String.
    :return: [string]. An array of transformed file names.
    """
    img = Image(filename=f_name)

    flopped = img.clone()
    flopped.flop()
    name_flopped = filename.split('.', 1)[0] + '_flopped.'+filename.split('.', 1)[1]
    f_name_flopped = os.path.join(app.config['UPLOAD_FOLDER'], name_flopped)
    flopped.save(filename=f_name_flopped)
    s3.meta.client.upload_file(f_name_flopped, 'ece1779xdz', name_flopped)

    rotated = img.clone()
    rotated.rotate(45)
    name_rotated = filename.split('.', 1)[0] + '_rotated.'+filename.split('.', 1)[1]
    f_name_rotated = os.path.join(app.config['UPLOAD_FOLDER'], name_rotated)
    rotated.save(filename=f_name_rotated)
    s3.meta.client.upload_file(f_name_rotated, 'ece1779xdz', name_rotated)

    enhanced = img.clone()
    enhanced.evaluate(operator='rightshift', value=1, channel='blue')
    enhanced.evaluate(operator='leftshift', value=1, channel='red')
    name_enhanced = filename.split('.', 1)[0] + '_enhanced.'+filename.split('.', 1)[1]
    f_name_enhanced = os.path.join(app.config['UPLOAD_FOLDER'], name_enhanced)
    enhanced.save(filename=f_name_enhanced)
    s3.meta.client.upload_file(f_name_enhanced, 'ece1779xdz', name_enhanced)

    return [name_flopped, name_rotated, name_enhanced]


@login_manager.user_loader
def user_loader(user_id):
    """Given *user_id*, return the associated User object.
    :param unicode user_id: user_id (email) user to retrieve
    """
    return Users.query.get(user_id)


def is_safe_url(target):
    """
    Checks if the url is save to redirect
    :param target: String.
    :return: Bool. 
    """
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def allowed_file(filename):
    """
    Checks if the file's extension is allowed and whether the filename already exists. 
    :param filename: String. 
    :return: Bool. True if file is allowed and False if not
    """
    if '.' in filename and filename.split('.', 1)[1].lower() not in app.config['ALLOWED_EXTENSIONS']:
        flash('Incorrect file extension. Please choose a png, jpg, jpeg or gif image.')
        return False
    return True

if __name__ == "__main__":
    # execute only if run as a script
    app.run(host='0.0.0.0',port=5001)
