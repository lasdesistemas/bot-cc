import requests, os, logging, json, psycopg2, time
from slack import WebClient
from slack.errors import SlackApiError
from flask import Flask, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

database_url = os.environ['DATABASE_URL']
slack_token = os.environ["SLACK_API_TOKEN"]

conn = psycopg2.connect(database_url, sslmode='require')
message_yes="Gracias! Registramos que aceptaste nuestro <https://github.com/lasdesistemas/codigo-de-conducta|Código de Conducta>.\nNo hace falta que hagas nada más. :smile:"
message_no="Procederemos a eliminar tu usuario. Si crees que hubo algún error o tenés dudas por favor escribinos a info@lasdesistemas.org"
client = WebClient(slack_token)

@app.route('/cc/responses/save', methods=['POST'])
def save():
    response = json.loads(request.form["payload"])
    user_id = response["user"]["id"]
    user_name = response["user"]["username"]
    name = response["user"]["name"]
    option = response["actions"][0]["value"]
    app.logger.info("User %s (%s) selected option: %s", user_name, user_id, option)
    accepted = option == "click_yes"
    register_response(user_id, user_name, accepted)
    message = message_yes if accepted else message_no
    try:
        response = client.chat_postMessage(
    		channel=user_id, 
    		blocks=[{
    			"type": "section",
    			"text": {
    				"type": "mrkdwn",
    				"text": message
                }
            }])
    except SlackApiError as e:
        app.logger.error("Unable to respond to user %s (%s): %s" % (user_name, user_id, e))
    return ""

def register_response(user_id, user_name, accepted):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cc_responses (user_id, user_name, accepted, timestamp) 
        VALUES ('%s', '%s', '%s', now()) 
        """ % (user_id, user_name, accepted))
    conn.commit()
    cur.close()

def get_pending_users(users):
    cur = conn.cursor()
    cur.execute("SELECT distinct user_id FROM cc_responses where accepted is not null")
    existing = list(map(lambda u: u[0], cur.fetchall()))
    pending = list(filter(lambda u: u["id"] not in existing, users))
    cur.close()
    return pending;

def get_recent_users():
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM cc_message_sent group by user_id HAVING max(timestamp) > (current_timestamp - interval '10 days')")
    recent = list(map(lambda u: u[0], cur.fetchall()))
    cur.close()
    return recent;

def insert_pending_response(user_id):
    cur = conn.cursor()
    cur.execute("INSERT INTO cc_message_sent (user_id, timestamp) values ('%s', now())" % user_id)
    conn.commit()
    cur.close()

@app.route('/cc/send-pending', methods=['POST'])
def send_messges():
    for page in client.users_list(limit=500):
        members_list = page["members"]
        users  = list(filter(lambda u: not u["is_bot"] and not u["deleted"] and u["id"] != "USLACKBOT", members_list))
        pending = get_pending_users(users)
        recent = get_recent_users()

        for user in pending:
            if user["id"] not in recent:
                try:
                    user_id = user["id"]
                    user_name = user["name"]
                    app.logger.info("Sending message to user %s (%s)" % (user_name, user_id))
                    response = client.chat_postMessage(
                        channel=user_id, 
                        text="Código de Conducta",
                        blocks='''[{
                            "type": "section",
                            "text": {
                                    "type": "mrkdwn",
                                    "text": "Hola! ¿Aceptas nuestro <https://github.com/lasdesistemas/codigo-de-conducta|Código de Conducta>?\nEn caso de no aceptar procederemos a eliminar tu usuario del Slack en los próximos días.\nSi detectas algún inconveniente para continuar por favor contacta a <https://lasdesistemas.slack.com/account/workspace-settings#admins|les admins>."}
                                }, 
                                {
                                    "type": "actions",
                                    "elements": [{"type": "button","text": {"type": "plain_text","text": "Sí! :tada:","emoji": true},"value": "click_yes"},
                                                 {"type": "button","text": {"type": "plain_text","text": "No :cry:","emoji": true},"value": "click_no"}]
                                }]''')  
                    insert_pending_response(user_id)

                except SlackApiError as e:
                    app.logger.error("Unable to send message to user %s (%s): %s" % (user_name, user_id, e))
    
    return "Mensajes enviados"

if __name__ == '__main__':
    app.run()

