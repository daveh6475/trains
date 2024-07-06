import requests
import re
from datetime import date
from dataclasses import dataclass
from typing import Any, List, Tuple
import xmltodict

@dataclass
class ProcessedDepartures:
    uid: str
    destination_name: str
    aimed_departure_time: str
    expected_departure_time: str
    status: str
    mode: str
    platform: str
    timetable_url: str
    toc: str

@dataclass
class CallingPoints:
    station: str
    arrival_time: str

def removeBrackets(originalName):
    return re.split(r" \(", originalName)[0]

def isTime(value):
    matches = re.findall(r"\d{2}:\d{2}", value)
    return len(matches) > 0

def joinwithCommas(listIN):
    return ", ".join(listIN)[::-1].replace(",", "dna ", 1)[::-1]

def removeEmptyStrings(items):
    return filter(None, items)

def joinWith(items, joiner: str):
    filtered_list = removeEmptyStrings(items)
    return joiner.join(filtered_list)

def joinWithSpaces(*args):
    return joinWith(args, " ")

def prepareServiceMessage(operator):
    return joinWithSpaces("A" if operator not in ['Elizabeth Line', 'Avanti West Coast'] else "An", operator, "Service")

def prepareLocationName(location, show_departure_time):
    location_name = removeBrackets(location['locationName'])
    if not show_departure_time:
        return location_name
    else:
        scheduled_time = location["st"]
        try:
            expected_time = location["et"]
        except KeyError:
            # as per api docs, it's 'at' if there isn't an 'et':
            expected_time = location["at"]
        departure_time = expected_time if isTime(expected_time) else scheduled_time
        formatted_departure = joinWith(["(", departure_time, ")"], "")
        return joinWithSpaces(location_name, formatted_departure)

def prepareCarriagesMessage(carriages):
    if carriages == 0:
        return ""
    else:
        return joinWithSpaces("formed of", carriages, "coaches.")

def ArrivalOrder(ServicesIN):
    ServicesOUT = []
    for servicenum, eachService in enumerate(ServicesIN):
        STDHour = int(eachService['std'][0:2])
        STDMinute = int(eachService['std'][3:5])
        if (STDHour < 2):
            STDHour += 24  # this prevents a 12am departure displaying before a 11pm departure
        STDinMinutes = STDHour * 60 + STDMinute  # this service is at this many minutes past midnight
        ServicesOUT.append(eachService)
        ServicesOUT[servicenum]['sortOrder'] = STDinMinutes
    ServicesOUT = sorted(ServicesOUT, key=lambda k: k['sortOrder'])
    return ServicesOUT

def ProcessDepartures(journeyConfig, APIOut):
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    data = APIOut
    Services = []

    # get departure station name
    departureStationName = data['locationName']

    if 'trainServices' in data:
        Services = data['trainServices']
        if isinstance(Services, dict):  # if there's only one service, it comes out as a dict
            Services = [Services]       # but it needs to be a list with a single element

        # if there are train and bus services from this station
        if 'busServices' in data:
            BusServices = data['busServices']
            if isinstance(BusServices, dict):
                BusServices = [BusServices]
            Services = ArrivalOrder(Services + BusServices)  # sort the bus and train services into one list in order of scheduled arrival time

    elif 'busServices' in data:
        Services = data['busServices']
        if isinstance(Services, dict):
            Services = [Services]

    else:
        Services = None
        return None, departureStationName

    Departures = [{}] * len(Services)

    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}

        if 'platform' in eachService:
            thisDeparture["platform"] = eachService['platform']

        thisDeparture["aimed_departure_time"] = eachService["std"]
        thisDeparture["expected_departure_time"] = eachService["etd"]

        if 'length' in eachService:
            thisDeparture["carriages"] = eachService["length"]
        else:
            thisDeparture["carriages"] = 0

        if 'operator' in eachService:
            thisDeparture["operator"] = eachService["operator"]

        if not isinstance(eachService['destination']['location'], list):    
            thisDeparture["destination_name"] = removeBrackets(eachService['destination']['location']['locationName'])
        else:  
            DestinationList = [i['locationName'] for i in eachService['destination']['location']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

        if 'subsequentCallingPoints' in eachService:  
            if not isinstance(eachService['subsequentCallingPoints']['callingPointList'], dict):
                CallingPointList = eachService['subsequentCallingPoints']['callingPointList']
                CallLists = []
                CallListJoined = []
                for sectionNum, eachSection in enumerate(CallingPointList):
                    if isinstance(eachSection['callingPoint'], dict):
                        CallLists.append([prepareLocationName(eachSection['callingPoint'], show_individual_departure_time)])
                        CallListJoined.append(CallLists[sectionNum])
                    else:  
                        CallLists.append([prepareLocationName(i, show_individual_departure_time) for i in eachSection['callingPoint']])
                        CallListJoined.append(joinwithCommas(CallLists[sectionNum]))
                thisDeparture["calling_at_list"] = joinWithSpaces(
                    " with a portion going to ".join(CallListJoined),
                    "  --  ",
                    prepareServiceMessage(thisDeparture["operator"]),
                    prepareCarriagesMessage(thisDeparture["carriages"])
                )
            else:  
                if isinstance(eachService['subsequentCallingPoints']['callingPointList']['callingPoint'], dict):
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(eachService['subsequentCallingPoints']['callingPointList']['callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:  
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in eachService['subsequentCallingPoints']['callingPointList']['callingPoint']]
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        joinwithCommas(CallList) + ".",
                        " --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
        else:  
            thisDeparture["calling_at_list"] = joinWithSpaces(
                thisDeparture["destination_name"],
                "only.",
                prepareServiceMessage(thisDeparture["operator"]),
                prepareCarriagesMessage(thisDeparture["carriages"])
            )

        Departures[servicenum] = thisDeparture

    return Departures, departureStationName

def loadDeparturesForStationRTT(journeyConfig, username: str, password: str) -> Tuple[List[ProcessedDepartures], str]:
    if journeyConfig["departureStation"] == "":
        raise ValueError("Please set the journey.departureStation property in config.json")

    if username == "" or password == "":
        raise ValueError("Please complete the rttApi section of your config.json file")

    departureStation = journeyConfig["departureStation"]

    response = requests.get(f"https://api.rtt.io/api/v1/json/search/{departureStation}", auth=(username, password))
    data = response.json()
    translated_departures = []
    td = date.today()

    if data['services'] is None:
        return translated_departures, departureStation

    for item in data['services'][:5]:
        uid = item['serviceUid']
        destination_name = item['locationDetail']['destination'][0]['description']

        dt = item['locationDetail']['gbttBookedDeparture']
        try:
            edt = item['locationDetail']['realtimeDeparture']
        except:
            edt = item['locationDetail']['gbttBookedDeparture']

        aimed_departure_time = dt[:2] + ':' + dt[2:]
        expected_departure_time = edt[:2] + ':' + edt[2:]
        status = item['locationDetail']['displayAs']
        mode = item['serviceType']
        try:
            platform = item['locationDetail']['platform']
        except:
            platform = ""

        toc = item["atocName"]

        translated_departures.append(
            ProcessedDepartures(
                uid=uid, destination_name=destination_name, aimed_departure_time=aimed_departure_time,
                expected_departure_time=expected_departure_time, status=status, mode=mode, platform=platform,
                timetable_url=f"https://api.rtt.io/api/v1/json/service/{uid}/{td.year}/{td.month:02}/{td.day:02}",
                toc=toc
            )
        )

    return translated_departures, departureStation

def loadDestinationsForDepartureRTT(journeyConfig: dict[str, Any], username: str, password: str, timetableUrl: str) -> List[CallingPoints]:
    r = requests.get(url=timetableUrl, auth=(username, password))
    calling_data = r.json()

    index = 0
    for loc in calling_data['locations']:
        if loc['crs'] == journeyConfig["departureStation"]:
            break
        index += 1

    calling_at = []    
    for loc in calling_data['locations'][index+1:]:
        calling_at.append(
            CallingPoints(loc['description'], loc["realtimeArrival"])
        )

    return calling_at

def loadDeparturesForStation(journeyConfig, apiKey, rows):
    if journeyConfig["departureStation"] == "":
        raise ValueError("Please configure the departureStation environment variable")

    if apiKey is None:
        raise ValueError("Please configure the apiKey environment variable")

    APIRequest = """
        <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">
        <x:Header>
            <typ4:AccessToken><typ4:TokenValue>""" + apiKey + """</typ4:TokenValue></typ4:AccessToken>
        </x:Header>
        <x:Body>
            <ldb:GetDepBoardWithDetailsRequest>
                <ldb:numRows>""" + rows + """</ldb:numRows>
                <ldb:crs>""" + journeyConfig["departureStation"] + """</ldb:crs>
                <ldb:timeOffset>""" + journeyConfig["timeOffset"] + """</ldb:timeOffset>
                <ldb:filterCrs>""" + journeyConfig["destinationStation"] + """</ldb:filterCrs>
                <ldb:filterType>to</ldb:filterType>
                <ldb:timeWindow>120</ldb:timeWindow>
            </ldb:GetDepBoardWithDetailsRequest>
        </x:Body>
    </x:Envelope>"""

    headers = {'Content-Type': 'text/xml'}
    apiURL = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"

    APIOut = requests.post(apiURL, data=APIRequest, headers=headers).text

    Departures, departureStationName = ProcessDepartures(journeyConfig, APIOut)

    return Departures, departureStationName

