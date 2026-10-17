"""
Trip Planner: Weather + Budget
------------------------------
Planning a trip? Enter where you're going and your budget, and this tool
tells you:
  - the weather there right now and over the next few days
  - what your budget is worth in the local currency
  - a simple packing tip

How it works (API chaining):
  1. OpenWeatherMap (current weather) -> finds the city and its country code
  2. OpenWeatherMap (5-day forecast)  -> the next few days for that city
  3. ExchangeRate-API (currency pair) -> converts your budget into the
                                         local currency of that country
  The results are combined into one report and saved to a JSON file.

Usage:
    python trip_planner.py

Requirements:
    pip install -r requirements.txt
    A .env file containing:
        OPENWEATHER_API_KEY=your_openweather_key
        EXCHANGE_API_KEY=your_exchangerate_api_key
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from babel.numbers import get_territory_currencies, list_currencies
from dotenv import load_dotenv

TIMEOUT = 10  # seconds
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
EXCHANGE_URL = "https://v6.exchangerate-api.com/v6/{key}/pair/{base}/{target}/{amount}"

LINE = "=" * 52

# Everyday abbreviations people type -> official ISO currency codes
CURRENCY_ALIASES = {
    "KSH": "KES", "KSHS": "KES",   # Kenya shilling
    "USH": "UGX", "USHS": "UGX",   # Uganda shilling
    "TSH": "TZS", "TSHS": "TZS",   # Tanzania shilling
    "RS": "INR", "NAIRA": "NGN", "RAND": "ZAR",
    "DOLLAR": "USD", "EURO": "EUR", "POUND": "GBP",
}


class TripError(Exception):
    """A problem we can explain to the user in plain English."""


# ---------------------------------------------------------------- setup

def load_keys():
    load_dotenv()
    weather_key = (os.getenv("OPENWEATHER_API_KEY") or "").strip()
    exchange_key = (os.getenv("EXCHANGE_API_KEY") or "").strip()
    missing = [name for name, val in
               (("OPENWEATHER_API_KEY", weather_key), ("EXCHANGE_API_KEY", exchange_key))
               if not val]
    if missing:
        raise TripError(f"Missing in your .env file: {', '.join(missing)}")
    return weather_key, exchange_key


def get_user_input():
    city = input("Where are you going? (city): ").strip()
    if not city:
        raise TripError("No city entered.")

    typed = input("Your home currency [KES]: ").strip().upper() or "KES"
    home = CURRENCY_ALIASES.get(typed, typed)
    if home not in list_currencies():
        raise TripError(f"'{typed}' is not a currency code. Use codes like KES, USD, EUR, GBP.")
    if home != typed:
        print(f"(Using {home}, the official code for {typed})")

    raw = input(f"Your budget in {home}: ").strip().replace(",", "")
    try:
        budget = float(raw)
    except ValueError:
        raise TripError(f"'{raw}' is not a number.")
    if budget <= 0:
        raise TripError("Budget must be more than zero.")

    return city, home, budget


# ---------------------------------------------------------------- API calls

def safe_get(url, params=None):
    """GET with friendly messages for network problems."""
    try:
        return requests.get(url, params=params, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        raise TripError("A service took too long to respond. Try again.")
    except requests.exceptions.ConnectionError:
        raise TripError("Couldn't connect. Check your internet connection.")


def check_weather_status(response, city):
    if response.status_code == 200:
        return response.json()
    if response.status_code == 401:
        raise TripError("Weather API key is invalid or not active yet. Check your .env file.")
    if response.status_code == 404:
        raise TripError(f"Couldn't find a city called '{city}'. Check the spelling.")
    if response.status_code == 429:
        raise TripError("Too many weather requests. Wait a minute and try again.")
    raise TripError(f"Weather service error (HTTP {response.status_code}).")


def get_current_weather(city, key):
    """API call 1."""
    params = {"q": city, "appid": key, "units": "metric"}
    return check_weather_status(safe_get(WEATHER_URL, params), city)


def get_forecast(lat, lon, key):
    """API call 2 - uses the coordinates found by call 1."""
    params = {"lat": lat, "lon": lon, "appid": key, "units": "metric"}
    return check_weather_status(safe_get(FORECAST_URL, params), "that location")


def convert_budget(key, home, local, amount):
    """API call 3 - uses the country found by call 1."""
    url = EXCHANGE_URL.format(key=key, base=home, target=local, amount=f"{amount:g}")
    response = safe_get(url)
    if response.status_code == 429:
        raise TripError("Too many currency requests. Wait a minute and try again.")
    try:
        data = response.json()
    except ValueError:
        raise TripError(f"Currency service gave an unexpected reply (HTTP {response.status_code}).")
    if data.get("result") != "success":
        reasons = {
            "invalid-key": "Currency API key is invalid. Check EXCHANGE_API_KEY in .env.",
            "inactive-account": "Confirm your email with ExchangeRate-API to activate your key.",
            "quota-reached": "Monthly currency-request limit reached.",
            "unsupported-code": f"Currency '{home}' or '{local}' isn't supported.",
        }
        raise TripError(reasons.get(data.get("error-type"), f"Currency error: {data.get('error-type')}"))
    return data


# ---------------------------------------------------------------- combine

def local_currency_for(country_code):
    currencies = get_territory_currencies(country_code)
    if not currencies:
        raise TripError(f"Couldn't work out the currency for country '{country_code}'.")
    return currencies[0]


def summarise_forecast(forecast):
    """Turn 3-hourly forecast slots into one line per day (local time)."""
    offset = timedelta(seconds=forecast["city"]["timezone"])
    days = defaultdict(lambda: {"temps": [], "rain": 0.0, "conditions": defaultdict(int)})

    for slot in forecast["list"]:
        local_time = datetime.fromtimestamp(slot["dt"], tz=timezone.utc) + offset
        day = days[local_time.date()]
        day["temps"].append(slot["main"]["temp"])
        day["rain"] = max(day["rain"], slot.get("pop", 0))
        day["conditions"][slot["weather"][0]["description"]] += 1

    summary = []
    for date in sorted(days)[:4]:
        d = days[date]
        summary.append({
            "date": date.isoformat(),
            "low_c": round(min(d["temps"]), 1),
            "high_c": round(max(d["temps"]), 1),
            "rain_chance_pct": round(d["rain"] * 100),
            "condition": max(d["conditions"], key=d["conditions"].get),
        })
    return summary


def packing_tip(current, days):
    highest = max([current["main"]["temp"]] + [d["high_c"] for d in days])
    lowest = min([current["main"]["temp"]] + [d["low_c"] for d in days])
    wettest = max([d["rain_chance_pct"] for d in days] or [0])
    tips = []
    if lowest < 10:
        tips.append("a warm jacket")
    elif lowest < 17:
        tips.append("a sweater for the evenings")
    if highest > 28:
        tips.append("light clothes and sunscreen")
    if wettest >= 50:
        tips.append("an umbrella")
    if not tips:
        return "Comfortable everyday clothes will do."
    if len(tips) == 1:
        return f"Pack {tips[0]}."
    return f"Pack {', '.join(tips[:-1])} and {tips[-1]}."


def build_report(city_input, home, budget, current, forecast, exchange):
    days = summarise_forecast(forecast)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trip": {"city_searched": city_input, "home_currency": home, "budget": budget},
        "destination": {
            "city": current["name"],
            "country_code": current["sys"]["country"],
            "local_currency": exchange["target_code"],
        },
        "weather_now": {
            "condition": current["weather"][0]["description"],
            "temp_c": current["main"]["temp"],
            "feels_like_c": current["main"]["feels_like"],
            "humidity_pct": current["main"]["humidity"],
            "wind_kmh": round(current["wind"]["speed"] * 3.6, 1),
        },
        "forecast": days,
        "money": {
            "rate": exchange["conversion_rate"],
            "budget_in_local": exchange["conversion_result"],
            "rates_updated": exchange["time_last_update_utc"],
        },
        "packing_tip": packing_tip(current, days),
    }


# ---------------------------------------------------------------- output

def save_to_file(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nFull report saved to {filename}")


def print_report(r):
    dest, now, money, trip = r["destination"], r["weather_now"], r["money"], r["trip"]
    home, local = trip["home_currency"], dest["local_currency"]

    print("\n" + LINE)
    print(f"  TRIP PLANNER: {dest['city']}, {dest['country_code']}")
    print(LINE)

    print("\n  WEATHER RIGHT NOW")
    print(f"  {'Conditions:':<14}{now['condition'].capitalize()}")
    print(f"  {'Temperature:':<14}{now['temp_c']:.1f} °C (feels like {now['feels_like_c']:.1f} °C)")
    print(f"  {'Humidity:':<14}{now['humidity_pct']}%")
    print(f"  {'Wind:':<14}{now['wind_kmh']:.1f} km/h")

    print("\n  NEXT FEW DAYS")
    for d in r["forecast"]:
        label = datetime.fromisoformat(d["date"]).strftime("%a %d %b")
        print(f"  {label:<12}{d['low_c']:>4.0f}–{d['high_c']:.0f} °C  "
              f"{d['condition'].capitalize()}, {d['rain_chance_pct']}% rain")

    print("\n  YOUR MONEY")
    if home == local:
        print(f"  {local} is the local currency - no exchange needed.")
        print(f"  {'Budget:':<14}{trip['budget']:,.2f} {home}")
    else:
        print(f"  {'Budget:':<14}{trip['budget']:,.2f} {home}")
        print(f"  {'Worth:':<14}{money['budget_in_local']:,.2f} {local}")
        print(f"  {'Rate:':<14}1 {home} = {money['rate']:,.4f} {local}")
        print(f"  {'':<14}1 {local} = {1 / money['rate']:,.2f} {home}")

    print("\n  PACKING TIP")
    print(f"  {r['packing_tip']}")
    print("\n" + LINE)


# ---------------------------------------------------------------- main

def main():
    print("Trip Planner: Weather + Budget")
    print("------------------------------")
    try:
        weather_key, exchange_key = load_keys()
        city, home, budget = get_user_input()

        print(f"\nLooking up {city}...")
        current = get_current_weather(city, weather_key)                    # call 1
        coords = current["coord"]
        forecast = get_forecast(coords["lat"], coords["lon"], weather_key)  # call 2
        local = local_currency_for(current["sys"]["country"])
        exchange = convert_budget(exchange_key, home, local, budget)        # call 3

        report = build_report(city, home, budget, current, forecast, exchange)
        print_report(report)
        save_to_file(report, f"trip_{'_'.join(current['name'].lower().split())}.json")
    except TripError as err:
        print(f"\nSorry: {err}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")


if __name__ == "__main__":
    main()