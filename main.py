import asyncio
import websockets
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import uuid
from uvicorn import Config, Server


clients = {}
trip_media_history = {}

async def handle_client(websocket):
    trip_id = None
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                trip_id = data.get('trip_id')

                if not trip_id:
                    response = {"type": "error", "message": "Missing trip_id"}
                    await websocket.send(json.dumps(response))
                    continue

                if trip_id not in clients:
                    clients[trip_id] = set()
                    trip_media_history[trip_id] = []

                if websocket not in clients[trip_id]:
                    clients[trip_id].add(websocket)
                    print(f"Klient dołączył do trip_id: {trip_id}")

                if data['type'] == 'leader_position':
                    for client in clients[trip_id]:
                        await client.send(message)

                elif data['type'] == 'stop_trip':
                    for client in clients[trip_id]:
                        await client.send(message)
                    del clients[trip_id]
                    del trip_media_history[trip_id]
                    print(f"Lider zakończył trip o trip_id: {trip_id}")

                elif data["type"] == "sync_media":
                    print(f"Otrzymano wiadomość: {message}")
                    last_id = data["last_id"]
                    print(f"Synchronizacja klienta w trip_id: {trip_id}. Ostatnie ID: {last_id}")
                    media_history = trip_media_history[trip_id]
                    start_index = next((i for i, media in enumerate(media_history) if media["id"] == last_id), None)

                    if start_index is None:
                        print("ID nie znaleziono, przesyłanie całej historii.")
                        missing_messages = media_history
                    else:
                        print(f"ID znaleziono, przesyłanie wiadomości od indeksu {start_index + 1}.")
                        missing_messages = media_history[start_index + 1:]

                    for message in missing_messages:
                        print(message)
                        await websocket.send(json.dumps(message))

            except json.JSONDecodeError:
                response = {"type": "error", "message": "Invalid JSON"}
                await websocket.send(json.dumps(response))

    except websockets.ConnectionClosed:
        print(f"Klient z trip_id: {trip_id} się rozłączył.")
    finally:
        if trip_id and websocket in clients.get(trip_id, set()):
            clients[trip_id].remove(websocket)
            print(f"Klient opuścił trip_id: {trip_id}")

async def websocket_server():
    """Uruchamia serwer WebSocket."""
    print("WebSocket Server running on ws://0.0.0.0:50000")
    async with websockets.serve(handle_client, "0.0.0.0", 80):
        await asyncio.Future()  # Utrzymuje serwer w działaniu

app = FastAPI()
UPLOAD_DIR = "uploads"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload_media/")
async def upload_media(file: UploadFile, lat: str = Form(...), long: str = Form(...), trip_uuid: str = Form(...)):
    """Przesyłanie pliku na serwer."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    try:
        with open(file_path, "wb") as f:
            f.write(await file.read())

        notification = {
            "id": str(uuid.uuid4()),
            "type": "new_media",
            "filePath": f"/static/{file.filename}",
            "lat": lat,
            "long": long,
        }

        if trip_uuid in trip_media_history:
            trip_media_history[trip_uuid].append(notification)
            await broadcast_to_trip(trip_uuid, notification)

        return JSONResponse(content={"message": "File uploaded successfully", "path": file_path}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

async def broadcast_to_trip(trip_uuid, message):
    """Przesyła wiadomość do wszystkich klientów w ramach jednej wycieczki."""
    if trip_uuid in clients:
        message_json = json.dumps(message)
        await asyncio.gather(
            *[client.send(message_json) for client in clients[trip_uuid]]
        )

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

app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")

async def run_fastapi():
    """Uruchamia serwer FastAPI."""
    print("File Server running on http://0.0.0.0:55000")
    config = Config(app, host="0.0.0.0", port=55000, loop="asyncio")
    server = Server(config)
    await server.serve()

async def main():
    await asyncio.gather(
        websocket_server(),
        run_fastapi(),
    )

if __name__ == "__main__":
    asyncio.run(main())
