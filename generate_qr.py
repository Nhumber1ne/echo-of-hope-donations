import qrcode

donation_url = "https://echo-of-hope-donations.onrender.com"

qr = qrcode.make(donation_url)

qr.save("echo_of_hope_donation_qr.png")

print("QR Code generated successfully!")