# Trip Planner: Weather + Budget

A command-line tool for anyone planning a trip. Type in where you're going and how much money you're bringing. It tells you:

- **The weather** there right now and over the next few days
- **What your budget is worth** in the local currency
- **What to pack**, based on the temperatures and the chance of rain

## The problem it solves

Before a trip you usually check several places: a weather site for the destination, a currency converter for your budget, and maybe a search to find out what currency they use there. This tool does all of that in one step, from one question. It works out the destination's currency on its own, so you don't need to know that Japan uses JPY or that Germany uses EUR.

## How it works

The tool chains three API calls, so the answer from one becomes the question for the next:

```
Your city ──► OpenWeatherMap (current weather)
                 │  gives: coordinates + country code (e.g. GB)
                 ├──► OpenWeatherMap (5-day forecast for those coordinates)
                 └──► country code ──► local currency (GBP)
                                          └──► ExchangeRate-API (your budget → GBP)
```

The results are combined into one report, printed in plain English and saved to a JSON file (e.g. `trip_london.json`).

## Setup

1. Get two free API keys:
   - [OpenWeatherMap](https://openweathermap.org/api) (new keys can take up to 2 hours to activate)
   - [ExchangeRate-API](https://www.exchangerate-api.com)
2. Install the requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Create your `.env` file from the example and paste in your keys:
   ```bash
   cp .env.example .env
   ```
   ```dotenv
   OPENWEATHER_API_KEY=your_openweather_key
   EXCHANGE_API_KEY=your_exchangerate_api_key
   ```

## Run

```bash
python trip_planner.py
```

```
Trip Planner: Weather + Budget
------------------------------
Where are you going? (city): London
Your home currency [KES]:
Your budget in KES: 50,000

Looking up London...

====================================================
  TRIP PLANNER: London, GB
====================================================

  WEATHER RIGHT NOW
  Conditions:   Light rain
  Temperature:  11.4 °C (feels like 9.8 °C)
  Humidity:     81%
  Wind:         18.7 km/h

  NEXT FEW DAYS
  Sun 18 Oct     8–15 °C  Broken clouds, 60% rain
  Mon 19 Oct     8–15 °C  Broken clouds, 20% rain
  ...

  YOUR MONEY
  Budget:       50,000.00 KES
  Worth:        290.60 GBP
  Rate:         1 KES = 0.0058 GBP
                1 GBP = 172.06 KES

  PACKING TIP
  Pack a warm jacket and an umbrella.

====================================================

Full report saved to trip_london.json
```

Press Enter at the currency prompt to use KES.

## Errors handled

| Situation                                            | What you see                                              |
| ---------------------------------------------------- | --------------------------------------------------------- |
| City misspelled (HTTP 404)                           | "Couldn't find a city called 'Lndn'. Check the spelling." |
| Weather key wrong or not active (HTTP 401)           | Points you to your `.env` file                            |
| Too many requests (HTTP 429)                         | Asks you to wait a minute                                 |
| Currency key invalid / quota used up                 | Plain-English reason from ExchangeRate-API                |
| No internet / timeout                                | "Couldn't connect. Check your internet connection."       |
| Missing keys in `.env`                               | Names exactly which key is missing                        |
| Budget isn't a number, currency code isn't 3 letters | Explains what to type instead                             |

## Security

API keys live in `.env`, which is listed in `.gitignore` and never pushed. `.env.example` shows which keys are needed.

## Built with

Python, `requests`, `python-dotenv` and `babel` (maps a country to its currency). Part of AI Masterclass 2, Phase II, Week 1.
