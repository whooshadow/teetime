import requests
import calendar
import argparse
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None
import uuid

# Known course UUIDs (Sweetspot)
COURSE_UUIDS = {
    "brållsta 18 hål": "292e2543-f661-403f-b1d6-a5086d251061",
    "bodaholm": "ac165789-77f6-43c5-ae15-907ae3c4b814",
    "gripsholm": "9cec9190-3cf1-4177-90a6-c8b1c874a552",
    "international": "2ee26a65-028d-46e0-809d-635bf3c06a5a",
    "kings course": "c006a958-4c27-4a58-9442-627a7aebc843",
    "queens": "583bf680-75c3-4281-b78d-be5ebbcdac1f",
    "kyssinge": "f10b066a-205b-4690-af58-83c43cff55c1",
    "lindö dal": "e02768fc-caff-49b6-a86d-237179cf5ca8",
    "lindö park": "15a56a35-ec3f-4067-935f-45b38530c52e",
    "lindö äng": "6ec41746-b529-46bc-ac81-514095105d54",
    "riksten": "19ceb886-66ed-4489-9ddd-6e86642a22be",
    "stannum": "c4d2c938-43d7-4b07-9ddc-c679c769d28c",
    "waxholm": "410fdd67-a108-4b3f-8058-1ff66fc061c2",
}

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def resolve_course_uuid(course: str) -> str:
    val = (course or "").strip()
    try:
        uuid.UUID(val)
        return val
    except Exception:
        pass
    key = _norm(val)
    if key in COURSE_UUIDS:
        return COURSE_UUIDS[key]
    for name, cuuid in COURSE_UUIDS.items():
        if _norm(name).startswith(key) or key.startswith(_norm(name)):
            return cuuid
    raise KeyError(f"Unknown course: {course}. Known: {', '.join(COURSE_UUIDS.keys())}")

class SweetspotClient:
    def __init__(self):
        self.api_origin = "https://middleware.sweetspot.io"
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36",
            "Referer": "https://book.sweetspot.io/",
            "Origin": "https://book.sweetspot.io",
            "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _stockholm_fixed_tz(self, local_date: datetime):
        y = local_date.year
        last_dom_mar = calendar.monthrange(y, 3)[1]
        d_mar = datetime(y, 3, last_dom_mar)
        start_dst = last_dom_mar - ((d_mar.weekday() - 6) % 7)
        last_dom_oct = calendar.monthrange(y, 10)[1]
        d_oct = datetime(y, 10, last_dom_oct)
        end_dst = last_dom_oct - ((d_oct.weekday() - 6) % 7)
        in_dst = datetime(y, 3, start_dst).date() <= local_date.date() <= datetime(y, 10, end_dst).date()
        hours = 2 if in_dst else 1
        return timezone(timedelta(hours=hours))

    def _build_api_window_utc(self, date_str: str):
        naive = datetime.strptime(date_str, "%Y-%m-%d")
        if ZoneInfo is not None:
            try:
                tz = ZoneInfo("Europe/Stockholm")
            except Exception:
                tz = self._stockholm_fixed_tz(naive)
        else:
            tz = self._stockholm_fixed_tz(naive)
        local_day_start = naive.replace(tzinfo=tz)
        local_day_end = (local_day_start + timedelta(days=1)) - timedelta(milliseconds=1)
        start_utc = local_day_start.astimezone(timezone.utc)
        end_utc = local_day_end.astimezone(timezone.utc)
        to_iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return to_iso(start_utc), to_iso(end_utc)

    def fetch_tee_times(self, course_uuid: str, date_str: str, limit: int = 9999):
        after_iso, before_iso = self._build_api_window_utc(date_str)
        params = {
            "course.uuid": course_uuid,
            "from[after]": after_iso,
            "from[before]": before_iso,
            "limit": str(limit),
            "order[from]": "asc",
            "page": "1",
        }
        url = f"{self.api_origin}/api/tee-times"
        r = self.session.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        return items or []

def _to_local_hhmm(start_iso: str) -> str:
    dt_utc = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    tz_local = None
    if ZoneInfo is not None:
        try:
            tz_local = ZoneInfo("Europe/Stockholm")
        except Exception:
            tz_local = None
    if tz_local is None:
        tz_local = SweetspotClient()._stockholm_fixed_tz(dt_utc)  # quick fallback instance
    return dt_utc.astimezone(tz_local).strftime("%H:%M")

def _s(v): return v.strip().lower() if isinstance(v, str) else ""

def _tmin(hhmm: str | None) -> int | None:
    if not hhmm: return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sweetspot tee time finder (API only)")
    parser.add_argument("-m", "--players", type=int, choices=[1, 2, 3, 4], default=1, help="Group size (1-4)")
    parser.add_argument("-d", "--dates", help="Comma-separated dates YYYY-MM-DD (default: today)")
    parser.add_argument("-c", "--course", help="Optional single course name or UUID; default is all courses")
    parser.add_argument("-a", "--after", help="Earliest time HH:MM to include (optional)")
    parser.add_argument("-b", "--before", help="Latest time HH:MM to include (optional)")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    date_list = [d.strip() for d in (args.dates or today).split(",") if d.strip()]
    client = SweetspotClient()

    after_min = _tmin(args.after)
    before_min = _tmin(args.before)

    def in_window(hhmm: str) -> bool:
        t = _tmin(hhmm)
        if t is None: return False
        if after_min is not None and t < after_min: return False
        if before_min is not None and t > before_min: return False
        return True

    # Helper to process one course+date and print formatted output
    def process_course(course_label: str, cuuid: str, date_str: str):
        items = client.fetch_tee_times(cuuid, date_str)
        out = []
        for it in (items or []):
            # Category may be a dict; normalize for checks
            cat = it.get("category") or {}
            if isinstance(cat, dict):
                # Skip maintenance
                if _s(cat.get("name")) == "banunderhåll" or _s(cat.get("custom_name")) == "banunderhåll" or _s(it.get("name")) == "banunderhåll":
                    continue
                if _s(cat.get("display")) == "full":
                    continue
                if _s(cat.get("custom_name")) in {"fullbokad", "fullbokat", "fullbokade"}:
                    continue
                if cat.get("tee_time_bookable") is False:
                    continue
            else:
                # Fallback: legacy string category or name
                if (_s(it.get("name")) or _s(it.get("category"))) == "banunderhåll":
                    continue
            start_iso = it.get("from") or it.get("start")
            if not start_iso:
                continue
            hhmm = _to_local_hhmm(start_iso)
            if not in_window(hhmm):
                continue
            avail = it.get("available_slots")
            if not isinstance(avail, int):
                try:
                    avail = int(avail)
                except Exception:
                    avail = 0
            if avail >= args.players:
                out.append((hhmm, avail))
        out.sort(key=lambda x: _tmin(x[0]) or 1_000_000)
        # Print course title (Title Case)
        title = course_label.title()
        print(f"\n{title}")
        if not out:
            print(f"no match found for {title}")
        else:
            for hhmm, avail in out:
                print(f"  {hhmm}  slots:{avail}")

    try:
        if args.course:
            cuuid = resolve_course_uuid(args.course)
            label = next((n for n, u in COURSE_UUIDS.items() if u == cuuid), args.course)
            for d in date_list:
                process_course(label, cuuid, d)
        else:
            for d in date_list:
                for name, cuuid in COURSE_UUIDS.items():
                    process_course(name, cuuid, d)
    except Exception as e:
        print(f"Error: {e}")