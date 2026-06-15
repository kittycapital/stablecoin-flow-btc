import requests
import json
import time
from datetime import datetime, timezone

def fetch_stablecoin_data(coin_id):
    """DefiLlama stablecoin API - id 1=USDT, 2=USDC"""
    url = f"https://stablecoins.llama.fi/stablecoin/{coin_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    result = {}
    for entry in data.get("tokens", []):
        ts = entry["date"]
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        circulating = entry.get("circulating", {})
        mcap = circulating.get("peggedUSD", 0)
        if mcap and mcap > 0:
            result[date_str] = mcap
    
    return result

def fetch_btc_price():
    """CoinGecko daily BTC price - 무료 API, 키 불필요, 전체 히스토리"""
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {
        "vs_currency": "usd",
        "days": "max"
        # interval 파라미터 제거: days=max 시 자동으로 daily 반환 (무료 플랜 호환)
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    result = {}
    for entry in data.get("prices", []):
        ts_ms, price = entry[0], entry[1]
        date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if price and price > 0:
            result[date_str] = price
    
    return result

def compute_indicators(combined_mcap, btc_prices):
    """
    Compute:
    - 60-day market cap change
    - SMA(30) of 60-day change
    - Daily market cap change
    - Investment signals
    """
    dates = sorted(combined_mcap.keys())
    
    records = []
    for i, date in enumerate(dates):
        mcap = combined_mcap[date]
        btc = btc_prices.get(date, None)
        
        # 60-day change
        change_60d = None
        if i >= 60:
            past_date = dates[i - 60]
            past_mcap = combined_mcap[past_date]
            change_60d = mcap - past_mcap
        
        # Daily change
        daily_change = None
        if i >= 1:
            prev_date = dates[i - 1]
            prev_mcap = combined_mcap[prev_date]
            daily_change = mcap - prev_mcap
        
        records.append({
            "date": date,
            "btc_price": btc,
            "combined_mcap": round(mcap, 2),
            "change_60d": round(change_60d, 2) if change_60d is not None else None,
            "daily_change": round(daily_change, 2) if daily_change is not None else None,
            "sma_30": None  # computed below
        })
    
    # SMA(30) of 60-day change
    for i in range(len(records)):
        if i >= 29 and records[i]["change_60d"] is not None:
            vals = []
            for j in range(i - 29, i + 1):
                if records[j]["change_60d"] is not None:
                    vals.append(records[j]["change_60d"])
            if len(vals) == 30:
                records[i]["sma_30"] = round(sum(vals) / 30, 2)
    
    # Investment signals
    for i in range(1, len(records)):
        r = records[i]
        prev = records[i - 1]
        signal = None
        signal_type = None
        
        if r["change_60d"] is not None and prev["change_60d"] is not None:
            # Zero line crossover
            if prev["change_60d"] < 0 and r["change_60d"] >= 0:
                signal = "자금 유입 전환 (0선 상향 돌파)"
                signal_type = "bullish"
            elif prev["change_60d"] >= 0 and r["change_60d"] < 0:
                signal = "자금 유출 전환 (0선 하향 돌파)"
                signal_type = "bearish"
            
            # Extreme values
            if r["change_60d"] < -3_000_000_000:
                signal = "바닥 감지 구간 (극단 음수)"
                signal_type = "bottom"
            elif r["change_60d"] > 15_000_000_000:
                signal = "과열 경고 구간 (극단 양수)"
                signal_type = "overheat"
            
            # SMA cross
            if r["sma_30"] is not None and prev["sma_30"] is not None:
                prev_diff = prev["change_60d"] - prev["sma_30"]
                curr_diff = r["change_60d"] - r["sma_30"]
                if prev_diff < 0 and curr_diff >= 0 and signal is None:
                    signal = "모멘텀 상승 전환 (SMA 상향 돌파)"
                    signal_type = "momentum_up"
                elif prev_diff >= 0 and curr_diff < 0 and signal is None:
                    signal = "모멘텀 하락 전환 (SMA 하향 돌파)"
                    signal_type = "momentum_down"
        
        records[i]["signal"] = signal
        records[i]["signal_type"] = signal_type
    
    return records

def generate_summary(records):
    """Generate current status summary"""
    latest = None
    for r in reversed(records):
        if r["change_60d"] is not None:
            latest = r
            break
    
    if not latest:
        return {}
    
    # Find recent signal
    recent_signal = None
    for r in reversed(records):
        if r.get("signal"):
            recent_signal = r
            break
    
    # Determine status
    change = latest["change_60d"]
    if change < -3_000_000_000:
        status = "극단적 유출 (바닥 감지 구간)"
        status_color = "red"
    elif change < 0:
        status = "자금 유출 중"
        status_color = "orange"
    elif change < 5_000_000_000:
        status = "완만한 유입"
        status_color = "green"
    elif change < 15_000_000_000:
        status = "강한 유입"
        status_color = "blue"
    else:
        status = "과열 구간"
        status_color = "red"
    
    return {
        "date": latest["date"],
        "btc_price": latest["btc_price"],
        "combined_mcap": latest["combined_mcap"],
        "change_60d": latest["change_60d"],
        "daily_change": latest["daily_change"],
        "sma_30": latest["sma_30"],
        "status": status,
        "status_color": status_color,
        "recent_signal": recent_signal.get("signal") if recent_signal else None,
        "recent_signal_date": recent_signal.get("date") if recent_signal else None,
        "recent_signal_type": recent_signal.get("signal_type") if recent_signal else None
    }

def main():
    print("📡 Fetching USDT market cap from DefiLlama...")
    usdt = fetch_stablecoin_data(1)
    print(f"   → {len(usdt)} days of USDT data")
    
    time.sleep(1)
    
    print("📡 Fetching USDC market cap from DefiLlama...")
    usdc = fetch_stablecoin_data(2)
    print(f"   → {len(usdc)} days of USDC data")
    
    time.sleep(1)
    
    print("📡 Fetching BTC price from CoinGecko...")
    btc = fetch_btc_price()
    print(f"   → {len(btc)} days of BTC data")
    
    # Combine USDT + USDC
    all_dates = sorted(set(usdt.keys()) & set(usdc.keys()))
    combined = {}
    for d in all_dates:
        combined[d] = usdt.get(d, 0) + usdc.get(d, 0)
    
    print(f"✅ Combined stablecoin data: {len(combined)} days")
    print(f"   Period: {all_dates[0]} ~ {all_dates[-1]}")
    
    # Compute indicators
    print("🔧 Computing indicators...")
    records = compute_indicators(combined, btc)
    
    # Generate summary
    summary = generate_summary(records)
    
    # Also compute individual USDT/USDC for stacked chart
    individual = []
    for d in all_dates:
        individual.append({
            "date": d,
            "usdt_mcap": round(usdt.get(d, 0), 2),
            "usdc_mcap": round(usdc.get(d, 0), 2)
        })
    
    # Save output
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "data": records,
        "individual": individual
    }
    
    with open("stablecoin_btc_data.json", "w") as f:
        json.dump(output, f)
    
    print(f"💾 Saved stablecoin_btc_data.json")
    print(f"📊 Summary: {summary.get('status', 'N/A')}")
    print(f"   BTC: ${summary.get('btc_price', 'N/A'):,.0f}")
    print(f"   60d Change: ${summary.get('change_60d', 0):,.0f}")

if __name__ == "__main__":
    main()
