import json

curl_payload = '"[{\\"sequence\\":1,\\"type\\":\\"nps\\",\\"question\\":\\"Based on the availed home loan...\\",\\"answer\\":7}]"'

print("Raw:", curl_payload)
try:
    data = json.loads(curl_payload)
    print("Parsed once:", type(data), data)
    if isinstance(data, str):
        data2 = json.loads(data)
        print("Parsed twice:", type(data2), data2)
except Exception as e:
    print("Error:", e)
