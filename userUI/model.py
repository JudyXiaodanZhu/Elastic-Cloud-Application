from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship
from database import db


class Users(db.Model):
    __tablename__ = 'Users'

    email = db.Column(db.String(40), primary_key=True, unique=True, nullable=False)
    password = db.Column(db.String(120), unique=False, nullable=False)
    authenticated = db.Column(db.Boolean, default=False)
    images = relationship("Img")

    def is_active(self):
        """True, as all users are active."""
        return True

    def get_id(self):
        """Return the email address to satisfy Flask-Login's requirements."""
        return self.email

    def is_authenticated(self):
        """Return True if the user is authenticated."""
        return self.authenticated

    def is_anonymous(self):
        """False, as anonymous users aren't supported."""
        return False

    def __repr__(self):
        return '<User %r>' % self.email

    def __init__(self, email, password):
        self.email = email
        self.password = password


class Img(db.Model):
    __tablename__ = 'Img'

    img_name = db.Column(db.String(80), primary_key=True, unique=True, nullable=False)
    user_email = db.Column(db.String(80), ForeignKey('Users.email'), primary_key=True, unique=False, nullable=False)
    img_trans1 = db.Column(db.String(80), unique=False, nullable=True)
    img_trans2 = db.Column(db.String(80), unique=False, nullable=True)
    img_trans3 = db.Column(db.String(80), unique=False, nullable=True)

    def __init__(self, img_name, user_email):
        self.user_email = user_email
        self.img_name = img_name

    def __init__(self, img_name, user_email, trans1, trans2, trans3):
        self.user_email = user_email
        self.img_name = img_name
        self.img_trans1 = trans1
        self.img_trans2 = trans2
        self.img_trans3 = trans3