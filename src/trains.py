import requests
from datetime import date
from dataclasses import dataclass
from typing import Any

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


def abbrStation(journeyConfig: dict[str, Any], inputStr: str) -> str:
    dict = journeyConfig['stationAbbr']
    for key in dict.keys():
        inputStr = inputStr.replace(key, dict[key])
    return inputStr

def loadDeparturesForStationRTT(journeyConfig, username: str, password: str) -> tuple[list[ProcessedDepartures], str]:
    if journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please set the journey.departureStation property in config.json")

    if username == "" or password == "":
        raise ValueError(
            "Please complete the rttApi section of your config.json file")

    departureStation = journeyConfig["departureStation"]

    response = requests.get(f"https://api.rtt.io/api/v1/json/search/{departureStation}", auth=(username, password))
    data = response.json()
    translated_departures = []
    td = date.today()

    if data['services'] is None:
        return translated_departures, departureStation

    for item in data['services'][:5]:
        uid = item['serviceUid']
        destination_name = abbrStation(journeyConfig, item['locationDetail']['destination'][0]['description'])

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
                uid=uid, destination_name=abbrStation(journeyConfig, destination_name), aimed_departure_time=aimed_departure_time,
                expected_departure_time=expected_departure_time, status=status, mode=mode, platform=platform,
                timetable_url=f"https://api.rtt.io/api/v1/json/service/{uid}/{td.year}/{td.month:02}/{td.day:02}",
                toc=toc
            )
        )

    return translated_departures, departureStation

def loadDestinationsForDepartureRTT(journeyConfig: dict[str, Any], username: str, password: str, timetableUrl: str) -> list[CallingPoints]:
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
            CallingPoints(abbrStation(journeyConfig, loc['description']), loc["realtimeArrival"])
        )

    return calling_at
