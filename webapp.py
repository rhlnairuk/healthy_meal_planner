"""Local web UI for the meal planner: a menu view (this week + next week)
and editors for recipes, long-life ingredient classification, and ad-hoc
grocery items.

Usage:
    python3 webapp.py

Opens a browser tab at http://localhost:8765 (override with PORT/BROWSER_URL_HOST
env vars - see the Docker section in README.md). Stdlib only, single-threaded
(http.server.HTTPServer, not ThreadingHTTPServer) - deliberately, since this
is a single-user local tool and serializing all request handling removes
any read/write race on pantry_state.json / adhoc_items.json / recipes/*.json
without needing a lock.

Edits made through the recipe/long-life editors are written to
recipes/*.json and long_life_ingredients.json via a write-temp-file,
validate-with-the-existing-loader, atomic-replace sequence (see
_write_json_validated) - the real file is never observably half-written,
and an invalid edit leaves it untouched. Because meal_plan.py/grocery.py
cache their loaded data in module attributes at import time, every
successful write re-invokes the existing public loaders and reassigns just
those attributes (see refresh_recipe_pools/refresh_long_life_ingredients)
rather than reloading the modules, which would re-execute their dataclass
definitions and desync class identity from grocery.py/pantry.py's
already-bound references to them.
"""

import json
import os
import webbrowser
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import adhoc
import grocery
import household
import meal_plan
import pantry

# Bind to all interfaces so this also works published from inside a Docker
# container (where "localhost" would only mean the container's own loopback,
# unreachable from the host). BROWSER_URL_HOST is what's printed/opened -
# from the host's perspective a published container port is still reachable
# at localhost, so this stays "localhost" even though BIND_HOST doesn't.
BIND_HOST = "0.0.0.0"
BROWSER_URL_HOST = os.environ.get("BROWSER_URL_HOST", "localhost")
PORT = int(os.environ.get("PORT", "8765"))
WEB_DIR = Path(__file__).with_name("web")

STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/app.css": ("app.css", "text/css"),
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def refresh_recipe_pools() -> None:
    pools = meal_plan.load_recipe_pools()
    meal_plan.BREAKFASTS = pools["breakfasts"]
    meal_plan.LUNCHES = pools["lunches"]
    meal_plan.DINNERS = pools["dinners"]
    meal_plan.SNACKS = pools["snacks"]


def refresh_long_life_ingredients() -> None:
    grocery.LONG_LIFE_INGREDIENTS = grocery.load_long_life_ingredients()


def _write_json_validated(path: Path, data: list, validate) -> None:
    """Write data to path as JSON, but only after validate() (called on the
    temp file) succeeds - the real file is atomically replaced, never left
    half-written, and is untouched on validation failure.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    try:
        validate(tmp)
    except (ValueError, FileNotFoundError) as e:
        tmp.unlink(missing_ok=True)
        raise ApiError(str(e)) from None
    tmp.replace(path)


def _week_and_household(query: dict) -> tuple[int, int, int, list]:
    week = int(query.get("week", [None])[0]) if query.get("week", [None])[0] else date.today().isocalendar()[1]
    adults = int(query.get("adults", [2])[0])
    children = int(query.get("children", [1])[0])
    return week, adults, children, household.build_household(adults, children)


def _day_summary(day) -> dict:
    return {
        "day": day.day,
        "breakfast": day.breakfast.name,
        "lunch": day.lunch.name,
        "dinner": day.dinner.name,
        "snack": day.snack.name,
    }


def _recipe_detail(recipe) -> dict:
    return {"name": recipe.name, "steps": list(recipe.steps)}


def build_week_preview(week_number: int) -> dict:
    """Menu-only preview for a future week: no grocery/pantry access at
    all, so this can never accidentally trigger a purchase-tracking side
    effect for a week that isn't actionable yet.
    """
    week_plan = meal_plan.generate_week_plan(week_number)
    recipes = meal_plan._unique_recipes(week_plan)
    return {
        "week_number": week_number,
        "days": [_day_summary(d) for d in week_plan],
        "recipes": [_recipe_detail(r) for r in recipes],
    }


def build_plan_response(week_number: int, adults: int, children: int, hh: list) -> dict:
    portion_factor = household.total_portion_factor(hh)
    iso_year = date.today().isocalendar()[0]

    week_plan = meal_plan.generate_week_plan(week_number)
    weekly_items = grocery.build_weekly_grocery_list(week_plan, portion_factor)

    week_key = f"{iso_year}-W{week_number:02d}"
    adhoc_items = adhoc.load_items(week_key)

    biweekly_due = grocery.is_biweekly_shopping_week(week_number)
    biweekly = None
    if biweekly_due:
        next_week_plan_for_pantry = meal_plan.generate_week_plan(week_number + 1)
        shopping_cycle_id = f"{iso_year}-W{week_number:02d}"
        biweekly_items = pantry.plan_biweekly_purchase(
            week_plan, next_week_plan_for_pantry, portion_factor, shopping_cycle_id
        )
        biweekly = {"items": [asdict(i) | {"display": i.display()} for i in biweekly_items]}

    return {
        "household": {
            "adults": adults,
            "children": children,
            "description": household.describe(hh),
            "portion_factor": portion_factor,
        },
        "week_number": week_number,
        "week_key": week_key,
        "this_week": {
            "days": [_day_summary(d) for d in week_plan],
            "recipes": [_recipe_detail(r) for r in meal_plan._unique_recipes(week_plan)],
            "weekly_grocery": [asdict(i) | {"display": i.display()} for i in weekly_items],
            "adhoc": [asdict(i) | {"display": i.display()} for i in adhoc_items],
        },
        "next_week": build_week_preview(week_number + 1),
        "biweekly_due": biweekly_due,
        "biweekly": biweekly,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep stdout quiet for a local dev tool; errors still raise

    # ---- response helpers ----

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ApiError(f"Request body is not valid JSON: {e}") from None

    def _send_static(self, filename: str, content_type: str) -> None:
        path = WEB_DIR / filename
        if not path.exists():
            self._send_error_json(f"Not found: {filename}", 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routing ----

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            self._send_static(filename, content_type)
            return

        try:
            if path == "/api/plan":
                # Re-read recipes/*.json and long_life_ingredients.json from
                # disk before building the plan - not just for edits made
                # through this app's own editors (which already trigger a
                # refresh on write), but for edits made directly to the
                # files by hand, e.g. in a host-mounted volume under Docker.
                refresh_recipe_pools()
                refresh_long_life_ingredients()
                week, adults, children, hh = _week_and_household(query)
                self._send_json(build_plan_response(week, adults, children, hh))
            elif path.startswith("/api/recipes/"):
                self._handle_get_recipes(path)
            elif path == "/api/long-life":
                self._handle_get_long_life()
            elif path == "/api/adhoc":
                self._handle_get_adhoc(query)
            else:
                self._send_error_json(f"Not found: {path}", 404)
        except ApiError as e:
            self._send_error_json(e.message, e.status)
        except Exception as e:
            self._send_error_json(str(e), 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        try:
            body = self._read_json_body()
            if path.startswith("/api/recipes/"):
                self._handle_post_recipe(path, body)
            elif path == "/api/long-life":
                self._handle_post_long_life(body)
            elif path == "/api/adhoc":
                self._handle_post_adhoc(query, body)
            elif path == "/api/reset-pantry":
                pantry.reset_state()
                self._send_json({"ok": True})
            else:
                self._send_error_json(f"Not found: {path}", 404)
        except ApiError as e:
            self._send_error_json(e.message, e.status)
        except Exception as e:
            self._send_error_json(str(e), 500)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
            if path.startswith("/api/recipes/"):
                self._handle_put_recipe(path, body)
            elif path.startswith("/api/long-life/"):
                self._handle_put_long_life(path, body)
            else:
                self._send_error_json(f"Not found: {path}", 404)
        except ApiError as e:
            self._send_error_json(e.message, e.status)
        except Exception as e:
            self._send_error_json(str(e), 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/recipes/"):
                self._handle_delete_recipe(path)
            elif path.startswith("/api/long-life/"):
                self._handle_delete_long_life(path)
            elif path.startswith("/api/adhoc/"):
                self._handle_delete_adhoc(path)
            else:
                self._send_error_json(f"Not found: {path}", 404)
        except ApiError as e:
            self._send_error_json(e.message, e.status)
        except Exception as e:
            self._send_error_json(str(e), 500)

    # ---- recipes ----

    def _slot_from_path(self, path: str, expect_index: bool) -> tuple[str, int | None]:
        # /api/recipes/<slot> or /api/recipes/<slot>/<index>
        parts = path.split("/")[3:]  # ["", "api", "recipes", slot, (index)]
        if not parts or not parts[0]:
            raise ApiError("Missing meal slot in path.", 404)
        slot = parts[0]
        if slot not in meal_plan.MEAL_SLOTS:
            raise ApiError(f"Unknown meal slot '{slot}'; must be one of {meal_plan.MEAL_SLOTS}.", 404)
        index = None
        if expect_index:
            if len(parts) < 2:
                raise ApiError("Missing recipe index in path.", 404)
            try:
                index = int(parts[1])
            except ValueError:
                raise ApiError(f"Invalid recipe index: {parts[1]!r}.", 400) from None
        return slot, index

    def _slot_path(self, slot: str) -> Path:
        return meal_plan.RECIPES_DIR / f"{slot}.json"

    def _handle_get_recipes(self, path: str) -> None:
        slot, _ = self._slot_from_path(path, expect_index=False)
        recipes = json.loads(self._slot_path(slot).read_text())
        self._send_json(recipes)

    def _handle_post_recipe(self, path: str, body: dict) -> None:
        slot, _ = self._slot_from_path(path, expect_index=False)
        slot_path = self._slot_path(slot)
        recipes = json.loads(slot_path.read_text())
        recipes.append(body)
        _write_json_validated(slot_path, recipes, lambda tmp: self._validate_slot_file(slot, tmp))
        refresh_recipe_pools()
        self._send_json(json.loads(slot_path.read_text()))

    def _validate_slot_file(self, slot: str, tmp_path: Path) -> None:
        raw = json.loads(tmp_path.read_text())
        for i, r in enumerate(raw):
            meal_plan._parse_recipe(f"{slot}.json", i, r)

    def _handle_put_recipe(self, path: str, body: dict) -> None:
        slot, index = self._slot_from_path(path, expect_index=True)
        slot_path = self._slot_path(slot)
        recipes = json.loads(slot_path.read_text())
        if index < 0 or index >= len(recipes):
            raise ApiError(f"No recipe at index {index} in {slot}.", 404)
        recipes[index] = body
        _write_json_validated(slot_path, recipes, lambda tmp: self._validate_slot_file(slot, tmp))
        refresh_recipe_pools()
        self._send_json(json.loads(slot_path.read_text()))

    def _handle_delete_recipe(self, path: str) -> None:
        slot, index = self._slot_from_path(path, expect_index=True)
        slot_path = self._slot_path(slot)
        recipes = json.loads(slot_path.read_text())
        if index < 0 or index >= len(recipes):
            raise ApiError(f"No recipe at index {index} in {slot}.", 404)
        recipes.pop(index)
        if not recipes:
            raise ApiError(f"Can't delete the last recipe in {slot} - each meal slot needs at least one.", 400)
        _write_json_validated(slot_path, recipes, lambda tmp: self._validate_slot_file(slot, tmp))
        refresh_recipe_pools()
        self._send_json(recipes)

    # ---- long-life ingredients ----

    def _handle_get_long_life(self) -> None:
        entries = json.loads(grocery.LONG_LIFE_PATH.read_text())
        self._send_json(entries)

    def _validate_long_life_file(self, tmp_path: Path) -> None:
        grocery.load_long_life_ingredients(tmp_path)

    def _handle_post_long_life(self, body: dict) -> None:
        entries = json.loads(grocery.LONG_LIFE_PATH.read_text())
        entries.append(body)
        _write_json_validated(grocery.LONG_LIFE_PATH, entries, self._validate_long_life_file)
        refresh_long_life_ingredients()
        self._send_json(json.loads(grocery.LONG_LIFE_PATH.read_text()))

    def _handle_put_long_life(self, path: str, body: dict) -> None:
        parts = path.split("/")[3:]  # ["", "api", "long-life", index]
        if not parts:
            raise ApiError("Missing long-life ingredient index in path.", 404)
        index = int(parts[0])
        entries = json.loads(grocery.LONG_LIFE_PATH.read_text())
        if index < 0 or index >= len(entries):
            raise ApiError(f"No long-life ingredient at index {index}.", 404)
        entries[index] = body
        _write_json_validated(grocery.LONG_LIFE_PATH, entries, self._validate_long_life_file)
        refresh_long_life_ingredients()
        self._send_json(json.loads(grocery.LONG_LIFE_PATH.read_text()))

    def _handle_delete_long_life(self, path: str) -> None:
        parts = path.split("/")[3:]
        if not parts:
            raise ApiError("Missing long-life ingredient index in path.", 404)
        index = int(parts[0])
        entries = json.loads(grocery.LONG_LIFE_PATH.read_text())
        if index < 0 or index >= len(entries):
            raise ApiError(f"No long-life ingredient at index {index}.", 404)
        entries.pop(index)
        _write_json_validated(grocery.LONG_LIFE_PATH, entries, self._validate_long_life_file)
        refresh_long_life_ingredients()
        self._send_json(entries)

    # ---- ad-hoc items ----

    def _handle_get_adhoc(self, query: dict) -> None:
        week_key = self._week_key_from_query(query)
        items = adhoc.load_items(week_key)
        self._send_json([asdict(i) | {"display": i.display()} for i in items])

    def _week_key_from_query(self, query: dict) -> str:
        week = query.get("week", [None])[0]
        if not week:
            raise ApiError("Missing 'week' query parameter.", 400)
        iso_year = date.today().isocalendar()[0]
        return f"{iso_year}-W{int(week):02d}"

    def _handle_post_adhoc(self, query: dict, body: dict) -> None:
        week_key = self._week_key_from_query(query)
        try:
            items = adhoc.add_item(week_key, body.get("name", ""), body.get("quantity"), body.get("unit", ""))
        except ValueError as e:
            raise ApiError(str(e)) from None
        self._send_json([asdict(i) | {"display": i.display()} for i in items])

    def _handle_delete_adhoc(self, path: str) -> None:
        # /api/adhoc/<week>/<index>
        parts = path.split("/")[3:]
        if len(parts) < 2:
            raise ApiError("Expected /api/adhoc/<week>/<index>.", 404)
        week, index_str = parts[0], parts[1]
        try:
            iso_year = date.today().isocalendar()[0]
            week_key = f"{iso_year}-W{int(week):02d}"
            index = int(index_str)
        except ValueError:
            raise ApiError("Invalid week or index in path.", 400) from None
        try:
            items = adhoc.remove_item(week_key, index)
        except IndexError as e:
            raise ApiError(str(e), 404) from None
        self._send_json([asdict(i) | {"display": i.display()} for i in items])


def main() -> None:
    server = HTTPServer((BIND_HOST, PORT), Handler)
    url = f"http://{BROWSER_URL_HOST}:{PORT}/"
    print(f"Serving the meal planner UI at {url} (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        pass  # no browser available (e.g. running inside a Docker container) - not fatal
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
