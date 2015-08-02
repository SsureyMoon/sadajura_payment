import json

from flask import Flask, render_template, Blueprint, request,\
    redirect, url_for, flash, jsonify, make_response

import httplib, httplib2
import base64
import urllib
import stripe

# configuration
DEBUG = True

app = Flask(__name__)
app.config.from_object(__name__)

app.debug = True

# Sabre
key = '<sabre-key>'
secret = '<sabre-secret>'

token = '<access_token>'

stripe.api_key = '<stripe-api-key>'

parseAppId = '<parse-api-id>'
parseAPIKey = '<parseAPIKey>'


@app.route("/")
def home():
    return jsonify(result="success")


@app.route("/account", methods=['POST',])
def create_account():
    if request.method == "POST":
        if request.headers.get('Athorization') != token:
            return make_response('token invalid', 401)
        form = json.loads(request.get_data())
        username = form.get('username')

        user = get_user_by_name(username)

        try:
            account = stripe.Account.create(
                managed=False,
                country='US',
                email=user.get('email') or username + '@example2.com'
            )
        except:
            accounts = stripe.Account.all(limit=10)
            print accounts
            for item in accounts.get('data'):
                print item
                if item.get('email') == (user.get('email') or username + '@example2.com'):
                    account = item
                    break
        return jsonify({'traveler_account': account.get('id')})



@app.route("/payment/<traveler_name>", methods=['POST',])
def create_payment(traveler_name):

    if request.method == "POST":
        if request.headers.get('Athorization') != token:
            return make_response('token invalid', 401)

        traveler = get_user_by_name(traveler_name)

        if not traveler.get('traveler_account'):
            return make_response('traveler should register stripe account first.'
                                 'It can be done at POST /account', 500)

        form = json.loads(request.get_data())

        email = form.get('email')

        number = form.get('number')
        exp_month = int(form.get('exp_month'))
        exp_year = int(form.get('exp_year'))
        cvc = int(form.get('cvc'))
        amount = float(form.get('amount'))

        customer = create_customer(email, number, exp_month, exp_year, cvc)
        customer_id = customer.id

        charge = stripe.Charge.create(
            amount=int(amount*100.0),
            currency="usd",
            customer=customer_id
        )

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        connection.connect()
        connection.request('POST', '/1/classes/Charge', json.dumps({
            "charge_id": charge.id,
            "traveler_id": {
                "__op": "AddRelation",
                "objects": [
                    {
                        "__type": "Pointer",
                        "className": "_User",
                        "objectId": traveler.get('objectId'),
                    }
                ]
            },

            "amount": amount,
            "is_done": False
        }), {
            "X-Parse-Application-Id": parseAppId,
            "X-Parse-REST-API-Key": parseAPIKey,
            "Content-Type": "application/json"
        })
        results = json.loads(connection.getresponse().read())

        return jsonify(results)


@app.route("/payment/<charge_id>/confirm", methods=['PUT',])
def payment_confirmed(charge_id):

    if request.method == "PUT":
        if request.headers.get('Athorization') != token:
            return make_response('token invalid', 401)

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        connection.connect()
        connection.request('GET', '/1/classes/Charge/'+charge_id, '', {
            "X-Parse-Application-Id": parseAppId,
            "X-Parse-REST-API-Key": parseAPIKey
        })

        result = json.loads(connection.getresponse().read())
        if result.get('is_done'):
            return "already done"

        stripe_charge_id = result.get('charge_id')
        amount = result.get('amount')

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        params = urllib.urlencode({"where":json.dumps({
            "$relatedTo": {
                "object": {
                    "__type": "Pointer",
                    "className": "Charge",
                    "objectId": result.get("objectId")
                },
                "key": "traveler_id"
            }
        })})

        connection.connect()
        connection.request('GET', '/1/users?%s' % params, '', {
            "X-Parse-Application-Id": parseAppId,
            "X-Parse-REST-API-Key": parseAPIKey
        })
        result = json.loads(connection.getresponse().read()).get('results')[0]
        push_id = result.get('objectId')
        traveler_account = result.get("traveler_account")
        email = result.get("email")
        transfer = stripe.Transfer.create(
            amount=int(float(amount)*100),
            currency="usd",
            destination=traveler_account,
            source_transaction=stripe_charge_id,
            description="Transfer for "+email
        )

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        connection.connect()
        connection.request('PUT', '/1/classes/Charge/'+charge_id, json.dumps({
               "is_done": True
        }), {
            "X-Parse-Application-Id": parseAppId,
            "X-Parse-REST-API-Key": parseAPIKey,
            "Content-Type": "application/json"
        })

        result = json.loads(connection.getresponse().read())

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        connection.connect()
        connection.request('POST', '/1/push', json.dumps({
               "channels": [
                 "user_" + push_id
               ],
                "data":{
                    "alert": "payment is successfully done + $:" + str(amount)
                }
             }), {
                "X-Parse-Application-Id": parseAppId,
                "X-Parse-REST-API-Key": parseAPIKey,
               "Content-Type": "application/json"
             })
        result = json.loads(connection.getresponse().read())
        return jsonify(transfer)


@app.route("/payment/<charge_id>/refund", methods=['PUT',])
def payment_canceled(charge_id):

    if request.method == "PUT":
        if request.headers.get('Athorization') != token:
            return make_response('token invalid', 401)

        connection = httplib.HTTPSConnection('api.parse.com', 443)
        connection.connect()
        connection.request('GET', '/1/classes/Charge/'+charge_id, '', {
            "X-Parse-Application-Id": parseAppId,
            "X-Parse-REST-API-Key": parseAPIKey
        })

        result = json.loads(connection.getresponse().read())
        if result.get('is_done'):
            return "already done"

        stripe_charge_id = result.get('charge_id')

        charge = stripe.Charge.retrieve(stripe_charge_id)
        refund = charge.refunds.create()

        return jsonify(refund)


@app.route("/return")
def return_test():
    print request
    return "return"


@app.route("/flights", methods=['GET', 'POST'])
def search_flights():

    if request.method == "GET":
        if request.headers.get('Athorization') != token:
            return make_response('token invalid', 401)
        insta_flight_url = 'https://api.test.sabre.com/v1/shop/flights'
        origin = request.args.get('origin', None)
        destination = request.args.get('destination', None)
        departuredate = request.args.get('departuredate', None)
        returndate = request.args.get('returndate', None)
        querystring = '?origin={0}&destination={1}&departuredate={2}&returndate={3}' \
                      '&onlineitinerariesonly=N&limit=10&offset=1' \
                      '&eticketsonly=N&sortby=totalfare&order=asc' \
                      '&sortby2=departuretime&order2=asc&pointofsalecountry=US'

        request_url = insta_flight_url + \
                      querystring.format(origin, destination, departuredate, returndate)
        print request_url
        access_token = getToken(key, secret)

        h = httplib2.Http()
        headers = {'Authorization': 'Bearer {}'.format(access_token)}
        response, content = h.request(request_url, "GET", headers=headers)
        content = json.loads(content)
        pricedList = content.get("PricedItineraries", None)

        if not pricedList:
            return "no data"
        itineraries = []
        options = []
        for item in pricedList:
            item2 = item.get('AirItinerary').get('OriginDestinationOptions').get('OriginDestinationOption')[0]
            tmp = item2.get('FlightSegment')
            DepartureDateTime =  tmp[0].get("DepartureDateTime")
            ArrivalDateTime =  tmp[1].get("ArrivalDateTime")
            itineraries.append(
            {
                'DepartureDateTime': DepartureDateTime,
                'ArrivalDateTime': ArrivalDateTime,
                "total_fare": item.get('AirItineraryPricingInfo')
                    .get('ItinTotalFare')
                    .get('TotalFare')
                    .get('Amount')
            })

        return jsonify({'itineraries': itineraries})

    if request.method == "POST":

        # print request.data
        # data_parsed = json.loads(str(request.data))
        # print data_parsed
        # insta_flight_url = 'https://api.test.sabre.com/v1/shop/flights'
        # origin = data_parsed.get('origin', None)
        # destination = data_parsed.get('destination', None)
        # departuredate = data_parsed.get('departuredate', None)
        # returndate = data_parsed.get('returndate', None)
        # querystring = '?origin={0}&destination={1}&departuredate={2}&returndate={3}' \
        #               '&onlineitinerariesonly=N&limit=10&offset=1' \
        #               '&eticketsonly=N&sortby=totalfare&order=asc' \
        #               '&sortby2=departuretime&order2=asc&pointofsalecountry=US'
        #
        # request_url = insta_flight_url + \
        #               querystring.format(origin, destination, departuredate, returndate)
        # print request_url
        # access_token = getToken(key, secret)
        #
        # h = httplib2.Http()
        # headers = {'Authorization': 'Bearer {}'.format(access_token)}
        # response, content = h.request(request_url, "GET", headers=headers)
        # return jsonify(content)
        return "1"


def getToken(id, secret):
    encoded = base64.b64encode(base64.b64encode(id)+':'+base64.b64encode(secret))
    h = httplib2.Http()
    headers = {'Content-type': 'application/x-www-form-urlencoded',
               'Authorization': 'Basic {}'.format(encoded)}
    response, content = h.request('https://api.test.sabre.com/v2/auth/token', "POST",
                                  headers=headers, body='grant_type=client_credentials')
    token = json.loads(content).get('access_token', None)
    return token


def create_customer(email, number, exp_month, exp_year, cvc):

    return stripe.Customer.create(
        description="Customer for test@example.com",
        email=email,
        source={
            "object": "card",
            "number": number,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "currency": "usd",
            "cvc": cvc
        }
    )


def get_user_by_name(username):
    connection = httplib.HTTPSConnection('api.parse.com', 443)
    params = urllib.urlencode({
        "where": json.dumps({
            "username": username
        })
    })

    connection.connect()
    connection.request('GET', '/1/users?%s' % params, '', {
       "X-Parse-Application-Id": parseAppId,
       "X-Parse-REST-API-Key": parseAPIKey
     })
    return json.loads(connection.getresponse().read()).get('results')[0]



if __name__ == "__main__":
    #app.run(host='127.0.0.1', port=8000)
    app.run(host='0.0.0.0', port=80)
