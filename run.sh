#!/bin/bash

# Check if config.json exists, if not, initialize an empty JSON file
if [ ! -f config.json ]; then
  echo '{}' > config.json
fi

# Update values in config.json
jq .journey.departureStation=\""${departureStation}"\" config.json | sponge config.json
jq .journey.destinationStation=\""${destinationStation}"\" config.json | sponge config.json
jq .journey.timeOffset=\""${timeOffset}"\" config.json | sponge config.json
jq .journey.outOfHoursName=\""${outOfHoursName}"\" config.json | sponge config.json
jq .refreshTime="${refreshTime}" config.json | sponge config.json
jq .transportApi.apiKey=\""${transportApi_apiKey}"\" config.json | sponge config.json
jq .transportApi.operatingHours=\""${transportApi_operatingHours}"\" config.json | sponge config.json

# Run the main Python script with display parameters
python3 ./src/main.py --display ssd1322 --width 256 --height 64 --interface spi --mode 1 --rotate 2
