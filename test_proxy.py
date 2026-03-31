import base64
import json
import httpx
import asyncio

url_b64 = "aHR0cHM6Ly9ycjItLS1zbi1ueG9xb3h1Y2ctbm41ZS5nb29nbGV2aWRlby5jb20vdmlkZW9wbGF5YmFjaz9leHBpcmU9MTc3NDk4OTc2OSZlaT1TY0hMYWZLcEc2WEgyTzhQMi1QZmtBZyZpcD0xNjguMjA1LjM3LjY1JmlkPTU1N2U0ZGM5YWM1MTM1OGImaXRhZz0xOCZzb3VyY2U9YmxvZ2dlciZyZXF1aXJlc3NsPXllcyZ4cGM9RWdobzdaZjNMbm9CQVE9PSZjcHM9MCZtZXQ9MTc3NDk2MDk2OSwmbWg9b3AmbW09MzEmbW49c24tbnhvcW94dWNnLW5uNWUmbXM9YXUmbXY9bSZtdmk9MiZwbD0yNCZybXM9YXUsYXUmc3VzYz1ibCZzdnB1Yz0xJmVhdWE9QWF6Mk55ZnlmaHcmbWltZT12aWRlby9tcDQmdnBydj0xJnJxaD0xJmR1cj0xNDQ0Ljk1NCZsbXQ9MTY2MTM0MTgxNDM1OTY0MyZtdD0xNzc0OTYwNDUxJnR4cD0xMzExMjI0JnNwYXJhbXM9ZXhwaXJlLGVpLGlwLGlkLGl0YWcsc291cmNlLHJlcXVpcmVzc2wseHBjLHN1c2Msc3ZwdWMsZWF1YSxtaW1lLHZwcnYscnFoLGR1cixsbXQmc2lnPUFIRXFOTTR3UmdJaEFQaEZ3d0tPbnJGbVpCdDFBeHo5X0xIODRlY2RVdnRtVTF2Z0JoeVZWMEVIQWlFQXVSQVZ4Rko1WkZRS2pCM3VYTkI3ZWpla2t6UHdFc1c4MWR2Z21Va2FxR289JmxzcGFyYW1zPWNwcyxtZXQsbWgsbW0sbW4sbXMsbXYsbXZpLHBsLHJtcyZsc2lnPUFQYVR4eE13UlFJZ0NWcndiZVVWSmFaVnppSFdZRjB3YVV5b3B4R3ljUnc4LV9qMVNEWHB1Nk1DSVFEN0JWa1d5QTBRT1dENjloLURpdFV2Vm5rU3AtWXA5LUdDejhYOEZfMk1ydz09JmNwbj1tY0FfMjItMTB3RkJEbnBhJmM9V0VCX0VNQkVEREVEX1BMQVlFUiZjdmVyPTEuMjAyNjAzMzEuMDAuMDAtY2FuYXJ5X2V4cGVyaW1lbnRfMS4yMDI2MDMyNS4xMC4wMA=="
headers_b64 = "eyJzZWMtY2gtdWEtcGxhdGZvcm0iOiAiXCJXaW5kb3dzXCIiLCAicmVmZXJlciI6ICJodHRwczovL3lvdXR1YmUuZ29vZ2xlYXBpcy5jb20vIiwgImFjY2VwdC1lbmNvZGluZyI6ICJpZGVudGl0eTtxPTEsICo7cT0wIiwgInVzZXItYWdlbnQiOiAiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMi4wLjAuMCBTYWZhcmkvNTM3LjM2IiwgInNlYy1jaC11YSI6ICJcIk5vdDpBLUJyYW5kXCI7dj1cIjk5XCIsIFwiSGVhZGxlc3NDaHJvbWVcIjt2PVwiMTQ1XCIsIFwiQ2hyb21pdW1cIjt2PVwiMTQ1XCIiLCAicmFuZ2UiOiAiYnl0ZXM9MC0iLCAic2VjLWNoLXVhLW1vYmlsZSI6ICI_MCJ9"

def pad_b64(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)

url = base64.urlsafe_b64decode(pad_b64(url_b64).encode()).decode("utf-8")
headers_str = base64.urlsafe_b64decode(pad_b64(headers_b64).encode()).decode("utf-8")
headers = json.loads(headers_str)

forbidden_headers = [
    "host", "connection", "accept-encoding", 
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"
]
headers = {k: v for k, v in headers.items() if k.lower() not in forbidden_headers}

async def test():
    async with httpx.AsyncClient(http2=True, verify=False) as client:
        req = client.build_request("GET", url, headers=headers)
        response = await client.send(req, stream=True)
        print("Status", response.status_code)
        if response.status_code >= 400:
            print("Content", await response.aread())
            print("Headers", response.headers)

asyncio.run(test())
