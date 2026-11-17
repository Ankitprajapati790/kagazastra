@echo off
cd "C:\Program Files\MongoDB\Server\9.0\bin"
mongod.exe --dbpath C:\data --port 27017 --bind_ip 127.0.0.1 --logpath C:\data\log\mongod.log