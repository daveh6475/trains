import os
import re
import json

def parsePlatformData(platformData):
    return platformData if platformData not in ["null", "undefined"] else None

def loadConfig(config_path='config.json'):
    # Load configuration from config.json file
    with open(config_path, 'r') as file:
        config = json.load(file)

    data = {
        "journey": {},
        "api": {}
    }

    # Populate data dictionary from config
    data["targetFPS"] = 70
    data["refreshTime"] = config.get("refreshTime", 180)
    data["fpsTime"] = 180
    data["screenRotation"] = 2
    data["screenBlankHours"] = ""
    data["headless"] = False
    data["debug"] = False

    data["dualScreen"] = config.get("dualScreen", False)
    data["firstDepartureBold"] = True
    data["hoursPattern"] = re.compile("^((2[0-3]|[0-1]?[0-9])-(2[0-3]|[0-1]?[0-9]))$")

    data["journey"]["departureStation"] = config.get("journey", {}).get("departureStation")
    data["journey"]["destinationStation"] = config.get("journey", {}).get("destinationStation", "")
    if data["journey"]["destinationStation"] in ["null", "undefined"]:
        data["journey"]["destinationStation"] = ""

    data["journey"]["individualStationDepartureTime"] = False
    data["journey"]["outOfHoursName"] = config.get("journey", {}).get("outOfHoursName", "London Paddington")
    data["journey"]["stationAbbr"] = config.get("journey", {}).get("stationAbbr", {"International": "Intl."})
    data["journey"]["timeOffset"] = config.get("journey", {}).get("timeOffset", "0")
    data["journey"]["screen1Platform"] = parsePlatformData(config.get("journey", {}).get("screen1Platform"))

    data["api"]["apiKey"] = config.get("api", {}).get("apiKey")
    data["api"]["apiUrl"] = config.get("api", {}).get("apiUrl")
    data["api"]["operatingHours"] = ""

    data["showDepartureNumbers"] = False

    return data

# Debugging information to ensure everything is loaded correctly
if __name__ == "__main__":
    config = loadConfig()
    print(f"API Key: {config['api']['apiKey']}")
    print(f"API URL: {config['api']['apiUrl']}")
    print(f"Departure Station: {config['journey']['departureStation']}")
