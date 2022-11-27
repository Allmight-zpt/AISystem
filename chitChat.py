from flask import Flask,request
import robot

app = Flask(__name__)

# 创建聊天机器人
myRobot0 = robot.robot('robot0')
myRobot1 = robot.robot('robot1')
myRobot2 = robot.robot('robot2')


@app.route('/chat',methods = ['GET','POST'])
def index():
    robotName = request.args.get('robotName')
    message = request.args.get('message')
    response = []
    if robotName == 'robot0':
        response = myRobot0.chitChat(message)
    elif robotName == 'robot1':
        response = myRobot1.chitChat(message)
    elif robotName == 'robot2':
        response = myRobot2.chitChat(message)
    return {
        'code' : 200 if len(response) != 0 else 400,
        'message' : "".join(response) 
    }

if __name__ == '__main__':
    app.run()