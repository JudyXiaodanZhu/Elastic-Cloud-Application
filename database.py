from flask_sqlalchemy import SQLAlchemy


def init_db(app):
    global db
    db = SQLAlchemy(app)

    from model import User, Img
    db.create_all()