import requests
import io
from PIL import Image

# Create a dummy image
img = Image.new('RGB', (100, 100), color = 'red')
img_byte_arr = io.BytesIO()
img.save(img_byte_arr, format='JPEG')
img_bytes = img_byte_arr.getvalue()

files = {'file': ('test.jpg', img_bytes, 'image/jpeg')}
# Mock session by ignoring it or just calling the endpoint if it allows without login
# Wait, /analyze requires @login_required
