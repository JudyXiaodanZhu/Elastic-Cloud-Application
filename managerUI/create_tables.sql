SHOW DATABASES;
USE ece1779;
CREATE TABLE IF NOT EXISTS Users(
    email varchar(40),
    password varchar(120),
    authenticated Boolean
);

CREATE TABLE Img(
    img_name varchar(80),
    user_email varchar(80),
    img_trans1 varchar(80),
    img_trans2 varchar(80),
    img_trans3 varchar(80)
);

CREATE TABLE auto_scale(
    upper FLOAT,
    lower FLOAT,
    grow int,
    shrink int,
    id int
);

INSERT INTO auto_scale VALUES (100,0,1,1,1);
