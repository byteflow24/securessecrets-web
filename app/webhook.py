import requests

url = "https://mood-reach-burn-ts.trycloudflare.com/webhook"

response = requests.post(url)

print(response.text)