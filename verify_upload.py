import mimetypes
import os
import sys
import uuid
from pathlib import Path
import httpx

BASE_URL = "http://localhost:8000/api/v1"

# Specify your image filename here, or leave empty to pick the first image found in the root
IMAGE_FILENAME = "image.png"


def find_image_file() -> Path:
    target = Path(IMAGE_FILENAME)
    if target.is_file():
        return target

    # Fallback: scan root folder for common image types
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    for file in Path(".").iterdir():
        if file.is_file() and file.suffix.lower() in extensions:
            return file

    print("Error: No image found in root directory.")
    print("Please place an image (e.g. 'product.jpg', 'image.png') in the root directory.")
    sys.exit(1)


def run():
    image_path = find_image_file()
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"

    file_size_kb = image_path.stat().st_size / 1024
    print(f"Using image: {image_path.name} ({file_size_kb:.1f} KB, MIME: {mime_type})")

    test_id = uuid.uuid4().hex[:6]
    email = f"seller_{test_id}@example.com"
    password = "SecurePassword123!"

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Register temporary seller
        print("\n[1/4] Registering test seller...")
        reg_res = client.post(
            "/auth/register",
            json={"email": email, "password": password, "full_name": "Real Image Tester"},
        )
        if reg_res.status_code != 201:
            print(f"Registration failed: {reg_res.text}")
            sys.exit(1)

        token = reg_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}
        print("      Authenticated.")

        # 2. Create product
        print("[2/4] Creating product in database...")
        prod_res = client.post(
            "/products",
            json={
                "title": f"Real Product Test {test_id}",
                "price": 7500.00,
                "inventory_count": 25,
            },
            headers=auth_headers,
        )
        if prod_res.status_code != 201:
            print(f"Product creation failed: {prod_res.text}")
            sys.exit(1)

        product_id = prod_res.json()["id"]
        print(f"      Product ID: {product_id}")

        # 3. Stream real file to upload endpoint
        print(f"[3/4] Uploading {image_path.name} to Cloudflare R2...")
        with open(image_path, "rb") as img_file:
            files = {"file": (image_path.name, img_file, mime_type)}
            upload_res = client.post(
                f"/products/{product_id}/image",
                files=files,
                headers=auth_headers,
            )

        if upload_res.status_code != 200:
            print(f"Upload failed ({upload_res.status_code}): {upload_res.text}")
            sys.exit(1)

        image_url = upload_res.json().get("image_url")
        print("      Upload successful!")
        print(f"      Public URL: {image_url}")

        # 4. Check if the file is reachable over the internet
        print("[4/4] Verifying public availability via GET...")
        with httpx.Client(timeout=15.0) as public_client:
            verify_res = public_client.get(image_url)
            if verify_res.status_code == 200:
                print(f"      Verified! Received HTTP 200 ({len(verify_res.content)} bytes).")
                print(f"\nYou can open this URL directly in your browser to view the image:\n{image_url}")
            else:
                print(f"      Returned HTTP {verify_res.status_code}: {verify_res.text}")


if __name__ == "__main__":
    run()