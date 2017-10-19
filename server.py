import os
from flask import Flask,request, flash, redirect, render_template,url_for,abort
from urllib.parse import urlparse, urljoin
from flask_login import LoginManager,login_user,logout_user,current_user,login_required
from passlib.hash import pbkdf2_sha256
import database
from werkzeug.utils import secure_filename
from wand.image import Image
from flask_thumbnails_wand import Thumbnail

file_path = os.path.abspath(os.getcwd())+"\database.db"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///'+file_path
app.config.from_pyfile('config.cfg')
database.init_db(app)
db = database.db
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])
thumb = Thumbnail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = u"Please login to access this page."
from model import User,Img
from forms import RegistrationForm,LoginForm

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('home'));
    return render_template('index.html');

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        next = request.args.get('next')
        # is_safe_url should check if the url is safe for redirects.
        if not is_safe_url(next):
            return abort(400)
        user = User.query.get(form.email.data)
        if user:
            user.authenticated = True
            db.session.add(user)
            db.session.commit()
            login_user(user,remember=True)
        return redirect(next or url_for('home'))
    return render_template('login.html',form=form,email=request.cookies.get('email'))

@app.route('/register',methods=['GET', 'POST'])
def register():
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        hash = pbkdf2_sha256.encrypt(form.password.data, rounds=200000, salt_size=16)
        user = User(form.email.data, hash)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash('User Registered！')
        return redirect(url_for('home'))
    return render_template('register.html',form=form)


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
    img=Img.query.filter_by(user_email=current_user.email)
    filename = []
    inputs = []
    if img:
        for field in img:
            inputs = [field.img_name,field.img_trans1,field.img_trans2,field.img_trans3]
            filename.append(inputs)
        print(filename)
    return render_template('dashboard.html',filename=filename)

@app.route('/test/FileUpload',methods=['GET','POST'])
def test():
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User.query.get(form.email.data)
        if not user:
            return render_template('fileUpload.html')
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        print(file.filename)
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            fname = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(fname)
            ftrans = transform(filename, fname)
            flash('Photo Uploaded!')
            img = Img(filename, user.email, ftrans[0], ftrans[1], ftrans[2])
            db.session.add(img)
            db.session.commit()
        return render_template('fileUpload.html',form=form)
    return render_template('fileUpload.html',form=form)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            fname = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(fname)
            ftrans = transform(filename, fname)
            flash('Photo Uploaded!')
            img = Img(filename,current_user.email,ftrans[0],ftrans[1],ftrans[2])
            db.session.add(img)
            db.session.commit()
            return redirect(url_for('upload_file',
                                    filename=filename))
    return render_template("upload.html")

def allowed_file(filename):
    image = Img.query.filter_by(img_name=filename).first()
    if image is not None:
        flash('Filename exist. Please change a name.')
        return False
    if '.' in filename and filename.split('.', 1)[1].lower() not in set([ 'png', 'jpg', 'jpeg', 'gif']):
        flash('Incorrect file extension. Please choose a png, jpg, jpeg or gif image.')
        return False
    return True

def transform(filename,fname):
    img = Image(filename=fname)
    flopped = img.clone()
    flopped.flop()
    fname_flopped = filename.split('.', 1)[0] + '_flopped.'+filename.split('.', 1)[1]
    flopped.save(filename=os.path.join(app.config['UPLOAD_FOLDER'], fname_flopped))
    rotated=img.clone()
    rotated.rotate(45)
    fname_rotated = filename.split('.', 1)[0] + '_rotated.'+filename.split('.', 1)[1]
    rotated.save(filename=os.path.join(app.config['UPLOAD_FOLDER'], fname_rotated))
    enhanced = img.clone()
    enhanced.evaluate(operator='rightshift', value=1, channel='blue')
    enhanced.evaluate(operator='leftshift', value=1, channel='red')
    fname_enhanced = filename.split('.', 1)[0] + '_enhanced.'+filename.split('.', 1)[1]
    enhanced.save(filename=os.path.join(app.config['UPLOAD_FOLDER'], fname_enhanced))
    return [fname_flopped,fname_rotated,fname_enhanced]

@login_manager.user_loader
def user_loader(user_id):
    """Given *user_id*, return the associated User object.

    :param unicode user_id: user_id (email) user to retrieve
    """
    return User.query.get(user_id)

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

if __name__ == "__main__":
    # execute only if run as a script
    app.run()