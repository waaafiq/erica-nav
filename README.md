# 🗺️ ERICA Nav

An unofficial campus map, shuttle timetable and class schedule for **Hanyang University ERICA**.

**[erica-nav.vercel.app](https://erica-nav.vercel.app)**

> Not affiliated with Hanyang University.

## Why

ERICA timetables list classes only by building and room number, and popular map apps are built for streets, not campuses. We ran a survey on wayfinding on campus: 64% of students had trouble finding the room inside a building, and Naver Map worked far worse for students who don't read Korean. We also found a trend: the less familiar students were with Korean, the more trouble they had finding buildings (33% of native Korean speakers, 53% of students with some Korean and 67% of students with none). ERICA Nav is built around building numbers and works in English and Korean.

## Features

- **Map:** search buildings by number or name, browse campus facilities (cafés, convenience stores, ATMs, print & copy and more), see building photos and floor counts, and get walking directions with a rotating compass map
- **Shuttle:** the shuttle bus timetable for semester, session and vacation periods, on weekdays and holidays
- **Timetable:** your own class schedule, linked to the buildings on the map
- **Saved:** save the places you go to most, kept on your device
- **English / 한국어:** switch languages at any time
- **Feedback:** send anonymous suggestions or complaints from the About tab

## Tech

- A single `index.html` with React, [Leaflet](https://leafletjs.com) (with [leaflet-rotate](https://github.com/Raruto/leaflet-rotate)) and GSAP, all vendored in `vendor/` so there's no build step
- Map tiles from [OpenStreetMap](https://www.openstreetmap.org); walking routes from the public [OSRM](https://project-osrm.org) server
- Hosted on [Vercel](https://vercel.com); `api/feedback.js` is a serverless function backed by Upstash Redis

## Editing the data

These CSV files are loaded by the app, so you can edit them in Excel or Google Sheets and the changes show up the next time the app loads.

| File | What it holds |
|:--|:--|
| `facilities.csv` | Facility types shown as filter chips |
| `building_facilities.csv` | Which facilities are in which building, and on which floor |
| `bus_timetable.csv` | Shuttle departures. The header comments explain every column and route code |

`buildings.csv` (building numbers, names and coordinates) is a reference list for the scripts in `tools/`. The app's own building data lives in `index.html`.

## Running locally

```sh
python3 -m http.server 8000
```

Then open http://localhost:8000. Everything works except sending feedback, which needs `vercel dev` and these environment variables:

- `KV_REST_API_URL` and `KV_REST_API_TOKEN` (or `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`)
- `FEEDBACK_ADMIN_KEY`, used by `feedback-admin.html` to export submissions as CSV

Check the feedback API with `node tools/test_feedback.js`.

## License

[GPL-3.0](LICENSE). Fonts are under the SIL Open Font License (see `fonts/`).
