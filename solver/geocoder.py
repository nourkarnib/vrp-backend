import httpx

async def geocode(address: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params, headers={"User-Agent": "vrp-app"})
        data = r.json()

    if not data:
        raise ValueError(f"Address not found: {address}")

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return (lat, lon)
