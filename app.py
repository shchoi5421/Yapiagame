import os, random, string, secrets, threading
from collections import defaultdict
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

MAX_PLAYERS = 6
rooms = {}
sid_to_player = {}
lock = threading.RLock()

ROLE_LABELS = {
    "mafia": "마피아",
    "doctor": "의사",
    "police": "경찰",
    "citizen": "시민",
}
ROLE_NAMES = {
    "mafia": "야동욱",
    "doctor": "안서현",
    "police": "경찰",
    "citizen": "시민",
}

def new_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in rooms:
            return code

def public_room(room):
    players = []
    for p in room["players"].values():
        players.append({
            "pid": p["pid"],
            "name": p["name"],
            "alive": p["alive"],
            "is_host": p["token"] == room["host"],
            "ready": p["ready"],
        })
    return {
        "code": room["code"],
        "players": players,
        "phase": room["phase"],
        "round": room["round"],
        "host": room["players"].get(room["host"], {}).get("pid"),
        "started": room["started"],
        "message": room.get("message", ""),
        "votes_cast": len(room.get("votes", {})),
        "alive_count": sum(1 for p in room["players"].values() if p["alive"]),
    }

def broadcast_room(code):
    room = rooms.get(code)
    if room:
        socketio.emit("room_update", public_room(room), to=code)

def private_role(code, player):
    if player.get("role"):
        socketio.emit("role_info", {
            "role": player["role"],
            "role_label": ROLE_LABELS[player["role"]],
            "role_name": ROLE_NAMES[player["role"]],
            "description": {
                "mafia": "밤에 제거할 플레이어 한 명을 선택하세요. 마피아끼리만 비밀 채팅을 할 수 있습니다.",
                "doctor": "밤마다 플레이어 한 명을 보호할 수 있습니다. 본인 보호도 가능합니다.",
                "police": "밤마다 살아 있는 플레이어 한 명을 조사해 마피아 여부를 확인합니다.",
                "citizen": "특별한 밤 능력은 없습니다. 낮 토론과 투표로 마피아를 찾아내세요.",
            }[player["role"]],
        }, to=player["sid"])

def player_by_token(room, token):
    return room["players"].get(token)

def current_player():
    return sid_to_player.get(request.sid)

def send_private(room, token, event, data):
    p = room["players"].get(token)
    if p and p.get("sid"):
        socketio.emit(event, data, to=p["sid"])

def system_message(room, message):
    room["message"] = message
    socketio.emit("system_message", {"message": message}, to=room["code"])

def check_winner(room):
    alive = [p for p in room["players"].values() if p["alive"]]
    mafia = [p for p in alive if p.get("role") == "mafia"]
    non_mafia = len(alive) - len(mafia)
    if not mafia:
        room["phase"] = "ended"
        room["message"] = "시민 팀 승리! 마피아가 모두 제거되었습니다."
        return "citizens"
    if len(mafia) >= non_mafia:
        room["phase"] = "ended"
        room["message"] = "마피아 승리! 마피아 수가 나머지 생존자 수 이상입니다."
        return "mafia"
    return None

def end_game(room, winner):
    room["phase"] = "ended"
    room["winner"] = winner
    labels = {"mafia": "마피아 팀", "citizens": "시민 팀"}
    room["message"] = f"{labels[winner]} 승리!"
    socketio.emit("game_over", {
        "winner": winner,
        "message": room["message"],
        "roles": [{"name": p["name"], "role": ROLE_LABELS.get(p.get("role"), "미배정"),
                   "role_name": ROLE_NAMES.get(p.get("role"), "")}
                  for p in room["players"].values()]
    }, to=room["code"])

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def connected():
    emit("connected", {"ok": True})

@socketio.on("create_room")
def create_room(data):
    name = (data.get("name") or "").strip()[:18]
    token = (data.get("token") or "").strip()[:80]
    if not name or not token:
        emit("error_message", {"message": "닉네임을 입력해 주세요."})
        return
    with lock:
        code = new_code()
        room = {
            "code": code, "players": {}, "host": token, "phase": "lobby",
            "round": 0, "started": False, "votes": {}, "night_actions": {},
            "night_results": [], "winner": None, "message": "친구를 초대하고 6명이 모이면 시작하세요."
        }
        room["players"][token] = {
            "token": token, "pid": secrets.token_urlsafe(8), "name": name, "sid": request.sid,
            "alive": True, "ready": True, "role": None
        }
        rooms[code] = room
        sid_to_player[request.sid] = {"code": code, "token": token}
        join_room(code)
        emit("joined_room", {"code": code, "pid": room["players"][token]["pid"], "is_host": True})
        broadcast_room(code)

@socketio.on("join_room")
def join_existing(data):
    code = (data.get("code") or "").strip().upper()[:5]
    name = (data.get("name") or "").strip()[:18]
    token = (data.get("token") or "").strip()[:80]
    if not code or not name or not token:
        emit("error_message", {"message": "방 코드와 닉네임을 입력해 주세요."})
        return
    with lock:
        room = rooms.get(code)
        if not room:
            emit("error_message", {"message": "방을 찾을 수 없습니다. 방 코드가 맞는지 확인하세요."})
            return
        existing = room["players"].get(token)
        if existing:
            existing["sid"] = request.sid
            existing["name"] = name
        elif room["started"]:
            emit("error_message", {"message": "게임이 이미 시작되어 새로 참가할 수 없습니다."})
            return
        elif len(room["players"]) >= MAX_PLAYERS:
            emit("error_message", {"message": "방이 가득 찼습니다. 최대 6명입니다."})
            return
        else:
            room["players"][token] = {
                "token": token, "pid": secrets.token_urlsafe(8), "name": name, "sid": request.sid,
                "alive": True, "ready": True, "role": None
            }
        sid_to_player[request.sid] = {"code": code, "token": token}
        join_room(code)
        emit("joined_room", {"code": code, "pid": room["players"][token]["pid"], "is_host": token == room["host"]})
        broadcast_room(code)
        if room["started"]:
            private_role(code, room["players"][token])
            emit("phase_update", {"phase": room["phase"], "round": room["round"],
                                  "message": room.get("message", "")})

@socketio.on("start_game")
def start_game():
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if not room or ctx["token"] != room["host"]:
        emit("error_message", {"message": "방장만 게임을 시작할 수 있습니다."})
        return
    if room["started"]:
        emit("error_message", {"message": "게임이 이미 시작되었습니다."})
        return
    if len(room["players"]) != MAX_PLAYERS:
        emit("error_message", {"message": "게임 시작에는 정확히 6명이 필요합니다."})
        return
    tokens = list(room["players"].keys())
    roles = ["mafia", "doctor", "police", "citizen", "citizen", "citizen"]
    random.shuffle(roles)
    for token, role in zip(tokens, roles):
        room["players"][token]["role"] = role
        room["players"][token]["alive"] = True
        private_role(room["code"], room["players"][token])
    room["started"] = True
    room["round"] = 1
    room["phase"] = "night"
    room["night_actions"] = {}
    room["votes"] = {}
    room["message"] = "밤이 되었습니다. 각 직업은 비밀 행동을 선택하세요."
    socketio.emit("phase_update", {"phase": "night", "round": 1, "message": room["message"]}, to=room["code"])
    broadcast_room(room["code"])
    system_message(room, room["message"])

@socketio.on("night_action")
def night_action(data):
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if not room or room["phase"] != "night":
        emit("error_message", {"message": "지금은 밤 행동을 할 수 없습니다."})
        return
    p = room["players"].get(ctx["token"])
    if not p or not p["alive"] or p.get("role") not in ("mafia", "doctor", "police"):
        emit("error_message", {"message": "밤 행동 권한이 없습니다."})
        return
    target_pid = data.get("target")
    target_token = next((t for t, item in room["players"].items() if item.get("pid") == target_pid), None)
    target = room["players"].get(target_token)
    if not target or not target["alive"] or target_token == p["token"] and p["role"] != "doctor":
        emit("error_message", {"message": "선택할 수 없는 대상입니다."})
        return
    room["night_actions"][p["role"]] = {"actor": p["token"], "target": target_token}
    send_private(room, p["token"], "action_ack", {"message": "선택이 접수되었습니다."})
    # Resolve when every living special-role player has submitted an action.
    required = {x["role"] for x in room["players"].values() if x["alive"] and x["role"] in ("mafia", "doctor", "police")}
    if required.issubset(room["night_actions"].keys()):
        resolve_night(room)
    else:
        broadcast_room(room["code"])

def resolve_night(room):
    actions = room["night_actions"]
    mafia_action = actions.get("mafia")
    doctor_action = actions.get("doctor")
    police_action = actions.get("police")
    # Police result is private and delivered only to the police.
    if police_action:
        target = room["players"].get(police_action["target"])
        actor = room["players"].get(police_action["actor"])
        if actor and actor["alive"] and target:
            send_private(room, actor["token"], "investigation_result", {
                "target": target["name"],
                "is_mafia": target.get("role") == "mafia",
                "message": f"조사 결과: {target['name']}은(는) " +
                           ("마피아입니다." if target.get("role") == "mafia" else "마피아가 아닙니다.")
            })
    eliminated = None
    if mafia_action:
        target_token = mafia_action["target"]
        protected = doctor_action and doctor_action["target"] == target_token
        target = room["players"].get(target_token)
        if target and target["alive"] and not protected:
            target["alive"] = False
            eliminated = target
    room["night_actions"] = {}
    room["votes"] = {}
    if eliminated:
        msg = f"아침이 밝았습니다. {eliminated['name']} 플레이어가 밤 사이 탈락했습니다."
    else:
        msg = "아침이 밝았습니다. 아무도 탈락하지 않았습니다."
    winner = check_winner(room)
    if winner:
        end_game(room, winner)
    else:
        room["phase"] = "day"
        room["message"] = msg
        socketio.emit("phase_update", {"phase": "day", "round": room["round"], "message": msg}, to=room["code"])
        system_message(room, msg)
    broadcast_room(room["code"])

@socketio.on("start_vote")
def start_vote():
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if not room or ctx["token"] != room["host"]:
        emit("error_message", {"message": "방장만 투표를 시작할 수 있습니다."})
        return
    if room["phase"] != "day":
        emit("error_message", {"message": "낮 토론 단계에서만 투표를 시작할 수 있습니다."})
        return
    room["phase"] = "vote"
    room["votes"] = {}
    room["message"] = "투표 시간입니다. 마피아라고 생각하는 플레이어를 선택하세요."
    socketio.emit("phase_update", {"phase": "vote", "round": room["round"], "message": room["message"]}, to=room["code"])
    system_message(room, room["message"])
    broadcast_room(room["code"])

@socketio.on("cast_vote")
def cast_vote(data):
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if not room or room["phase"] != "vote":
        emit("error_message", {"message": "지금은 투표할 수 없습니다."})
        return
    voter = room["players"].get(ctx["token"])
    target_pid = data.get("target")
    target_token = next((t for t, item in room["players"].items() if item.get("pid") == target_pid), None)
    target = room["players"].get(target_token)
    if not voter or not voter["alive"]:
        emit("error_message", {"message": "탈락한 플레이어는 투표할 수 없습니다."})
        return
    if not target or not target["alive"] or target_token == voter["token"]:
        emit("error_message", {"message": "자신 또는 탈락한 플레이어에게 투표할 수 없습니다."})
        return
    room["votes"][voter["token"]] = target_token
    emit("action_ack", {"message": "투표가 접수되었습니다."})
    alive_tokens = {t for t,p in room["players"].items() if p["alive"]}
    if alive_tokens.issubset(room["votes"].keys()):
        counts = defaultdict(int)
        for target_t in room["votes"].values():
            counts[target_t] += 1
        max_votes = max(counts.values()) if counts else 0
        winners = [t for t, count in counts.items() if count == max_votes]
        if len(winners) == 1:
            expelled = room["players"][winners[0]]
            expelled["alive"] = False
            msg = f"투표 결과, {expelled['name']} 플레이어가 탈락했습니다. ({max_votes}표)"
        else:
            msg = "투표가 동률입니다. 이번 낮에는 아무도 탈락하지 않았습니다."
        winner = check_winner(room)
        if winner:
            end_game(room, winner)
        else:
            room["phase"] = "day_result"
            room["message"] = msg
            socketio.emit("phase_update", {"phase": "day_result", "round": room["round"], "message": msg}, to=room["code"])
            system_message(room, msg)
    broadcast_room(room["code"])

@socketio.on("next_night")
def next_night():
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if not room or ctx["token"] != room["host"]:
        emit("error_message", {"message": "방장만 다음 밤을 시작할 수 있습니다."})
        return
    if room["phase"] != "day_result":
        emit("error_message", {"message": "투표 결과가 나온 뒤에 진행할 수 있습니다."})
        return
    room["round"] += 1
    room["phase"] = "night"
    room["night_actions"] = {}
    room["votes"] = {}
    room["message"] = f"{room['round']}번째 밤입니다. 각 직업은 비밀 행동을 선택하세요."
    socketio.emit("phase_update", {"phase": "night", "round": room["round"], "message": room["message"]}, to=room["code"])
    system_message(room, room["message"])
    broadcast_room(room["code"])

@socketio.on("chat_message")
def chat_message(data):
    ctx = current_player()
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    p = room["players"].get(ctx["token"]) if room else None
    message = (data.get("message") or "").strip()
    channel = data.get("channel", "public")
    if not room or not p or not message:
        return
    message = message[:300]
    if room["phase"] in ("lobby", "ended"):
        if room["phase"] == "ended":
            emit("error_message", {"message": "게임이 끝나 채팅할 수 없습니다."})
            return
    elif room["phase"] == "night":
        if channel != "mafia" or p.get("role") != "mafia" or not p["alive"]:
            emit("error_message", {"message": "밤에는 마피아 비밀 채팅만 사용할 수 있습니다."})
            return
    elif room["phase"] in ("day", "vote", "day_result"):
        if channel != "public" or not p["alive"]:
            emit("error_message", {"message": "낮에는 생존자만 전체 채팅을 사용할 수 있습니다."})
            return
    payload = {"name": p["name"], "message": message, "channel": channel}
    if channel == "mafia":
        mafia_sids = [x["sid"] for x in room["players"].values() if x.get("role") == "mafia" and x["alive"] and x.get("sid")]
        for sid in mafia_sids:
            socketio.emit("chat_message", payload, to=sid)
    else:
        socketio.emit("chat_message", payload, to=room["code"])

@socketio.on("disconnect")
def disconnected():
    ctx = sid_to_player.pop(request.sid, None)
    if not ctx:
        return
    room = rooms.get(ctx["code"])
    if room and ctx["token"] in room["players"]:
        room["players"][ctx["token"]]["sid"] = None
        broadcast_room(ctx["code"])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
