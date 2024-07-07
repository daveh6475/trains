import requests
import re
import json
from datetime import date
from dataclasses import dataclass
from typing import Any, List, Tuple

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
    location_name = removeBrackets(location['description'])
    if not show_departure_time:
        return location_name
    else:
        scheduled_time = location["gbttBookedArrival"]
        try:
            expected_time = location["realtimeArrival"]
        except KeyError:
            expected_time = location["gbttBookedArrival"]
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

def ProcessDepartures(journeyConfig, data):
    show_individual_departure_time = journeyConfig["individualStationDepartureTime"]
    Services = []

    # get departure station name
    departureStationName = data['location']['name']

    if 'services' in data:
        Services = data['services']
        if isinstance(Services, dict):  # if there's only one service, it comes out as a dict
            Services = [Services]       # but it needs to be a list with a single element

    else:
        Services = None
        return None, departureStationName

    Departures = [{}] * len(Services)

    for servicenum, eachService in enumerate(Services):
        thisDeparture = {}

        if 'platform' in eachService['locationDetail']:
            thisDeparture["platform"] = eachService['locationDetail']['platform']

        thisDeparture["aimed_departure_time"] = eachService['locationDetail']['gbttBookedDeparture']
        thisDeparture["expected_departure_time"] = eachService['locationDetail'].get("realtimeDeparture", thisDeparture["aimed_departure_time"])

        thisDeparture["carriages"] = 0  # Default value since the API does not provide carriages info

        thisDeparture["operator"] = eachService.get("atocName", "")

        if not isinstance(eachService['locationDetail']['destination'], list):    
            thisDeparture["destination_name"] = removeBrackets(eachService['locationDetail']['destination'][0]['description'])
        else:  
            DestinationList = [i['description'] for i in eachService['locationDetail']['destination']]
            thisDeparture["destination_name"] = " & ".join([removeBrackets(i) for i in DestinationList])

        if 'subsequentCallingPoints' in eachService['locationDetail']:  
            if isinstance(eachService['locationDetail']['subsequentCallingPoints'], list):
                CallingPointList = eachService['locationDetail']['subsequentCallingPoints']
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
                if isinstance(eachService['locationDetail']['subsequentCallingPoints']['callingPoint'], dict):
                    thisDeparture["calling_at_list"] = joinWithSpaces(
                        prepareLocationName(eachService['locationDetail']['subsequentCallingPoints']['callingPoint'], show_individual_departure_time),
                        "only.",
                        "  --  ",
                        prepareServiceMessage(thisDeparture["operator"]),
                        prepareCarriagesMessage(thisDeparture["carriages"])
                    )
                else:  
                    CallList = [prepareLocationName(i, show_individual_departure_time) for i in eachService['locationDetail']['subsequentCallingPoints']['callingPoint']]
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

    # Debug: Print the entire response from the API
    print("API response from search:", json.dumps(data, indent=2))

    translated_departures = []
    td = date.today()

    if 'services' not in data or data['services'] is None:
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

    # Debug: Print the entire response from the API
    print("API response from service:", json.dumps(calling_data, indent=2))

    departure_crs = journeyConfig["departureStation"].strip().lower()
    index = 0
    for loc in calling_data['locations']:
        if loc['crs'].strip().lower() == departure_crs:
            break
        index += 1

    print(f"Departure CRS: {departure_crs}, Stations: {[loc['crs'] for loc in calling_data['locations'][index+1:]]}")

    calling_at = []
    for loc in calling_data['locations'][index+1:]:
        calling_at.append(
            CallingPoints(loc['description'], loc["realtimeArrival"])
        )

    return calling_at

def loadDataRTT(apiConfig: dict[str, Any], journeyConfig: dict[str, Any]) -> Tuple[List[ProcessedDepartures], List[CallingPoints], str]:
    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if not isRun(runHours[0], runHours[1]):
        return [], [], journeyConfig['outOfHoursName']

    departures, stationName = loadDeparturesForStationRTT(journeyConfig, apiConfig["username"], apiConfig["password"])

    if len(departures) == 0:
        return [], [], journeyConfig['outOfHoursName']

    firstDepartureDestinations = loadDestinationsForDepartureRTT(journeyConfig, apiConfig["username"], apiConfig["password"], departures[0].timetable_url)

    return departures, firstDepartureDestinations, stationName

def isRun(start_hour, end_hour):
    current_hour = datetime.now().hour
    return start_hour <= current_hour < end_hour
