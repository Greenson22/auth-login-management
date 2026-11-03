from datetime import datetime, timezone

def parse_quota_info(remaining_fraction, reset_time):
    """
    Mengembalikan tuple: (formatted_text, is_reset_passed, color_hex, raw_percent, raw_timestamp)
    """
    # 1. Hitung Persentase
    percent_val = None
    if remaining_fraction is not None:
        try:
            percent_val = float(remaining_fraction) * 100
            percentage_str = f"{int(percent_val)}%"
        except (ValueError, TypeError):
            percentage_str = "-"
    else:
        percentage_str = "-"

    # Warna teks persentase
    if percent_val is None:
        text_color = "#888888"
    elif percent_val >= 70:
        text_color = "#2e7d32"
    elif percent_val >= 30:
        text_color = "#f57c00"
    else:
        text_color = "#c62828"

    # 2. Cek Reset Time
    formatted_time = "-"
    is_reset_passed = False
    raw_timestamp = 9999999999999  # Nilai default tinggi untuk sorting

    if reset_time and reset_time != "-":
        try:
            if str(reset_time).isdigit() or isinstance(reset_time, (int, float)):
                ts = float(reset_time)
                if ts > 1e11:
                    ts /= 1000.0
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                clean_str = reset_time.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_str)
            raw_timestamp = dt.timestamp()
            dt_local = dt.astimezone()
            formatted_time = dt_local.strftime("%d %b %Y, %H:%M")
            now = datetime.now(dt.tzinfo or timezone.utc)
            if dt <= now:
                is_reset_passed = True
        except Exception:
            formatted_time = str(reset_time)

    if percentage_str == "-" and formatted_time == "-":
        display_text = "-"
    else:
        display_text = f"{percentage_str} ({formatted_time})"

    return display_text, is_reset_passed, text_color, percent_val, raw_timestamp