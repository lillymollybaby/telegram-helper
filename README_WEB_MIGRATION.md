# Smart Assistant: Full Product Spec for Future Web Migration

## 1. Product Summary

This project is a Telegram smart assistant that combines:
- personal planning and travel reminders,
- food diary and nutrition coaching,
- movie tracking and movie-based English learning,
- sleep and hydration habit support,
- profile onboarding and personalization.

Primary audience: Russian-speaking users (current timezone focus: `Asia/Bishkek`), mobile-first usage.

Core UX principle: user writes naturally, assistant understands intent and asks only missing details.

---

## 2. Main User Value

- Convert natural messages into actionable plans.
- Reduce missed events with smart leave-time reminders.
- Build habits (sleep, water, meal tracking).
- Turn movie activity into learning content.

---

## 3. Current Platform and Stack

- Runtime: Python 3
- Bot framework: `python-telegram-bot` (job queue enabled)
- Scheduler: built-in PTB job queue (periodic and one-time jobs)
- DB: SQLite (`reminder.db`)
- HTTP client: `httpx`
- Date parsing: `dateparser`
- Env management: `python-dotenv`

Main files:
- `bot.py`: entrypoint + routing
- `app/planner.py`: planning, route/time logic, reminder scheduling
- `app/food.py`: meal flow and nutrition logic
- `app/movies.py`: Letterboxd/TMDB/movie learning
- `app/profile.py`: onboarding, profile editing, sleep/water reminders
- `app/db.py`: schema and data access
- `app/keyboards.py`: Telegram keyboards
- `app/config.py`: feature flags, labels, env settings

---

## 4. Feature Map (What Bot Can Do)

### 4.1 Personal Planning

- Detect planning intent from free text (ru).
- Parse/ask for:
  - origin address,
  - destination,
  - event time.
- Save task and schedule reminders.
- Estimate route travel time and suggest:
  - when to leave,
  - when to order taxi.
- Smart traffic checks before event.
- “My Plans” list and task deletion support.

### 4.2 Routing and Maps

Provider strategy:
- `auto` mode tries available providers in fallback order.
- Supports Google/Yandex/2GIS/OSRM fallbacks in code path.
- Current practical setup uses 2GIS key for route ETA.

Geocoding behavior:
- address normalization,
- city-aware fallback and coordinate parsing,
- graceful retry when address not recognized.

### 4.3 Food and Nutrition

- Add meal from text or photo.
- Store date/time and estimated macros:
  - calories, protein, fat, carbs, fiber.
- Daily summary and history.
- Dinner advice based on today’s intake.

### 4.4 Movies + Learning

- Letterboxd account linking via RSS.
- Detect new logs/wishlist updates.
- TMDB enrichment (actors/director/images where available).
- Learning cards based on watched movie:
  - facts,
  - cast/director learning,
  - English words and phrases.

### 4.5 Profile and Onboarding

First-run onboarding collects:
- name,
- city,
- timezone,
- home/work address,
- birth date,
- height/weight,
- activity level,
- goal,
- dietary restrictions,
- sleep/wake schedule,
- sleep/wake reminder offsets.

Each question explains “why this is needed”.

### 4.6 Sleep Reminders

Before sleep and before wake:
- asks confirmation with buttons:
  - yes,
  - no,
  - remind later.

### 4.7 Water Habit Logic

After onboarding:
- assistant suggests daily water target from weight (fallback default if weight absent).
- asks consent to enable hydration reminders.

Water reminders:
- asks if user drank water (`Yes`/`No`),
- if `Yes`: logs intake,
- if `No`: recalculates remaining plan to hit daily target.

---

## 5. Navigation Model (Telegram)

Main menu sections:
- Language Learning
- Movie
- Personal Planning
- Food
- Мой профиль

Important behavior:
- only navigation messages are auto-cleaned,
- important reminders/content persist longer,
- event reminders can be auto-cleaned after event time.

---

## 6. Data Model (Current SQLite)

Core tables:
- `users`
- `tasks`
- `letterboxd_subscriptions`
- `letterboxd_entries`
- `english_words`
- `food_profiles`
- `food_meals`
- `user_profiles`
- `water_logs`

Main entities:
- Task lifecycle: `scheduled` -> `sent`
- Profile lifecycle: onboarding incomplete -> complete
- Habit logs: meals and water entries by day/time

---

## 7. External Integrations

- Telegram Bot API
- Gemini API (NLU/extraction/content generation)
- 2GIS APIs (geocode/routing, depending on key access)
- Yandex APIs (optional/fallback where key access allows)
- Google Maps APIs (optional)
- TMDB API
- Letterboxd RSS feeds

---

## 8. Known Constraints

- SQLite on ephemeral hosting may lose state after restart/redeploy.
- API quotas/plan limits can affect route and content quality.
- Social/RSS sources can return 403/Cloudflare and require fallback parsing.

---

## 9. Recommended Next Technical Step

Before full web migration:
- move DB to managed Postgres/Supabase,
- separate business logic into service layer,
- expose REST/GraphQL API for web/mobile clients.

---

## 10. Web Migration Requirements (Mobile-First)

Target: responsive PWA/mobile web app replicating all current bot features.

### Must-have modules:
- Auth (Telegram Login/OAuth or phone/email)
- Dashboard (today timeline)
- Planning module (task create + route ETA + leave alerts)
- Food module (meal log + daily totals + AI advice)
- Movies module (feeds, details, learning content)
- Profile module (all onboarding/edit fields)
- Habit module (sleep/water reminder center)
- Notifications center (in-app + push settings)

### Must-have UX:
- quick actions from home screen,
- one-tap confirmation actions (yes/no/later),
- clear status cards: “event soon”, “water left today”, “sleep soon”.

### Must-have backend behavior:
- same reminder logic as bot,
- provider fallback for routing/geocoding,
- audit log for user actions (optional but recommended).

---

## 11. Ready-to-Use Prompt for “Rebuild as Mobile Web App”

Use this prompt as-is when asking an AI/dev team:

```
Rebuild my Telegram Smart Assistant as a mobile-first web app (PWA).

Current product has modules:
1) Personal Planning: parse natural text tasks, ask missing fields (origin/destination/time), calculate route ETA, suggest leave/order taxi times, traffic-aware reminders.
2) Food: meal logging from text/photo, calories/macros storage, daily summary/history, dinner suggestion.
3) Movies: Letterboxd RSS integration, detect watched/wishlist updates, TMDB enrichment, learning actions (actors/director/facts/English).
4) Profile: onboarding questionnaire (name, city, timezone, home/work, birth date, height/weight, activity, goal, restrictions, sleep/wake and reminder offsets).
5) Habits: sleep reminders (yes/no/later) and hydration reminders with dynamic recalculation to daily target.

Technical expectations:
- Mobile-first responsive UI.
- Backend API with scheduled jobs for reminders.
- Persistent DB (Postgres/Supabase).
- Push notifications and in-app notification center.
- Keep fallback strategy for route providers (2GIS/Yandex/Google/OSRM where applicable).
- Keep Russian-first UX text, but support i18n-ready structure.

Deliverables:
- Architecture diagram.
- DB schema.
- API endpoints.
- Screen map/wireframes.
- Migration plan from current Telegram SQLite state.
- Production deployment plan and monitoring.
```

---

## 12. Deployment Notes (Current)

- Prepared for Render worker deployment:
  - `render.yaml`
  - `Procfile`
  - `runtime.txt`
- Start command: `python bot.py`
- Build command: `pip install -r requirements.txt`

