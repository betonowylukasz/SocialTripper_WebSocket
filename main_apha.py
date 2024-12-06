import asyncio
import websockets
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from uvicorn import Config, Server
import json
import uuid

# Konfiguracja WebSocket
clients = set()
leader_socket = None  # Przechowuje WebSocket lidera

media_history = []

"""Obsługuje każdego klienta WebSocket."""
async def handle_client(websocket):
    global leader_socket
    clients.add(websocket)
    print("Nowy klient połączony.")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)

                if data['type'] == 'leaderPosition':
                    for client in clients:
                        if client != leader_socket:
                            await client.send(message)

                elif data["type"] == "sync_media":
                    print(f"Otrzymano wiadomość: {message}")
                    last_id = data["last_id"]
                    print(f"Synchronizacja klienta. Ostatnie ID: {last_id}")
                    start_index = next((i for i, media in enumerate(media_history) if media["id"] == last_id), None)
                    if start_index is None:
                        print("ID nie znaleziono, przesyłanie całej historii.")
                        missing_messages = media_history
                    else:
                        print(f"ID znaleziono, przesyłanie wiadomości od indeksu {start_index + 1}.")
                        missing_messages = media_history[start_index + 1:]

                    for message in missing_messages:
                        await websocket.send(json.dumps(message))

                elif data['type'] == 'request_route':
                    # Prośba uczestnika o trasę
                    if leader_socket:
                        await leader_socket.send(json.dumps({"type": "request_route"}))

                elif data['type'] == 'route_update':
                    # Lider wysyła aktualizację trasy
                    if websocket == leader_socket:
                        print("Aktualizacja trasy od lidera.")
                        for client in clients:
                            if client != leader_socket:
                                await client.send(message)

                else:
                    # Obsługa innych typów wiadomości
                    response = {"type": "error", "message": "Unknown type"}
                    await websocket.send(json.dumps(response))

            except json.JSONDecodeError:
                response = {"type": "error", "message": "Invalid JSON"}
                await websocket.send(json.dumps(response))

    except websockets.ConnectionClosed:
        print("Klient się rozłączył.")
    finally:
        if websocket == leader_socket:
            print("Lider się rozłączył.")
            leader_socket = None
        clients.remove(websocket)

async def websocket_server():
    """Uruchamia serwer WebSocket."""
    print("WebSocket Server running on ws://0.0.0.0:8080")
    async with websockets.serve(handle_client, "0.0.0.0", 8080):
        await asyncio.Future()  # Utrzymuje serwer w działaniu

# Konfiguracja API (FastAPI)
app = FastAPI()
UPLOAD_DIR = "uploads"

# Obsługa CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tworzenie katalogu na pliki
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload_media/")
async def upload_media(file: UploadFile, lat: str = Form(...), long: str = Form(...)):
    """Przesyłanie pliku na serwer."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    try:
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # Powiadomienie klientów przez WebSocket
        notification = {
            "id": str(uuid.uuid4()),
            "type": "new_media",
            "filePath": f"/static/{file.filename}",
            "lat": lat,
            "long": long,
        }

        media_history.append(notification)

        await broadcast_message(notification)

        return JSONResponse(content={"message": "File uploaded successfully", "path": file_path}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

async def broadcast_message(message: dict):
    """Wysyła wiadomość do wszystkich klientów."""
    if clients:
        message_json = json.dumps(message)
        await asyncio.gather(*[client.send(message_json) for client in clients])

@app.post("/upload/")
async def upload_file(file: UploadFile):
    """Przesyłanie pliku na serwer."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    return {"message": "File uploaded successfully", "path": file_path}

@app.get("/files/{filename}")
async def get_file(filename: str):
    """Pobieranie pliku z serwera."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

# Obsługa plików statycznych
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")

async def run_fastapi():
    """Uruchamia serwer FastAPI."""
    print("File Server running on http://0.0.0.0:8000")
    config = Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = Server(config)
    await server.serve()

# Uruchamianie obu serwerów jednocześnie
async def main():
    await asyncio.gather(
        websocket_server(),
        run_fastapi(),
    )

if __name__ == "__main__":
    asyncio.run(main())
