const socket = io();
const $ = id => document.getElementById(id);
const state = {token: localStorage.getItem("yapia_token") || crypto.randomUUID(), name:"", code:"", isHost:false, room:null, role:null, phase:"lobby", channel:"public", submitted:false, voted:false};
localStorage.setItem("yapia_token", state.token);
const roleSymbols = {mafia:"♠",doctor:"✚",police:"⌕",citizen:"♟"};
const phaseLabels = {lobby:"대기 중",night:"밤",day:"낮 토론",vote:"투표 중",day_result:"투표 결과",ended:"게임 종료"};
const avatarSymbols = ["♟","♜","♞","♝","♛","♚"];
function toast(message){$("toast").textContent=message;$("toast").classList.remove("hidden");clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").classList.add("hidden"),3000)}
function showGame(){ $("lobby-screen").classList.add("hidden");$("game-screen").classList.remove("hidden"); }
function showLobby(){ $("game-screen").classList.add("hidden");$("lobby-screen").classList.remove("hidden"); }
function me(){return state.room?.players.find(p=>p.pid===state.pid)}
function aliveTargets(allowSelf=false){return (state.room?.players||[]).filter(p=>p.alive&&(allowSelf||p.pid!==state.pid))}
function populateSelect(el, list){const old=el.value;el.innerHTML="";list.forEach(p=>{const o=document.createElement("option");o.value=p.pid;o.textContent=p.name+(p.pid===state.pid?" (나)":"");el.appendChild(o)});if([...el.options].some(o=>o.value===old))el.value=old}
function renderSeats(){
 const box=$("seats");box.innerHTML="";const players=state.room?.players||[];const n=Math.max(players.length,1);
 players.forEach((p,i)=>{
  const angle=(-90+i*(360/6))*Math.PI/180;const rx=42,ry=39;
  const seat=document.createElement("div");seat.className="seat"+(p.pid===state.pid?" me":"")+(p.alive?"":" dead");
  seat.style.left=(50+rx*Math.cos(angle))+"%";seat.style.top=(50+ry*Math.sin(angle))+"%";
  const avatar=document.createElement("div");avatar.className="avatar";avatar.textContent=avatarSymbols[i%avatarSymbols.length];
  const nm=document.createElement("div");nm.className="seat-name";nm.textContent=p.name;
  if(p.is_host){const c=document.createElement("span");c.className="host-crown";c.textContent="★";nm.appendChild(c)}
  const st=document.createElement("div");st.className="seat-state";st.textContent=p.alive?"● 생존":"✕ 탈락";
  seat.append(avatar,nm,st);box.appendChild(seat);
 });
 for(let i=players.length;i<6;i++){
  const angle=(-90+i*60)*Math.PI/180;const seat=document.createElement("div");seat.className="seat empty-seat";seat.style.left=(50+42*Math.cos(angle))+"%";seat.style.top=(50+39*Math.sin(angle))+"%";
  const a=document.createElement("div");a.className="avatar";a.textContent="+";a.style.opacity=".35";
  const nm=document.createElement("div");nm.className="seat-name";nm.style.color="#697386";nm.textContent="참가 대기 중";
  seat.append(a,nm);box.appendChild(seat);
 }
 $("player-count").textContent=players.length+" / 6명";
}
function renderRoom(room){
 state.room=room;state.code=room.code;state.phase=room.phase;state.isHost=room.host===state.pid;
 if(room.phase==="night"&&state.role?.role==="mafia") state.channel="mafia";
 else if(room.phase!=="night") state.channel="public";
 document.querySelectorAll(".chat-tab").forEach(b=>b.classList.toggle("active",b.dataset.channel===state.channel));
 $("chat-input").placeholder=state.channel==="mafia"?"마피아에게만 보이는 메시지...":"메시지를 입력하세요...";
 $("room-code-display").textContent=room.code;renderSeats();
 $("phase-badge").textContent=phaseLabels[room.phase]||room.phase;
 $("phase-message").textContent=room.message||"";
 $("center-title").textContent=({lobby:"밤이 오기 전",night:"밤이 찾아왔다",day:"아침이 밝았다",vote:"운명의 투표",day_result:"투표 결과",ended:"게임 종료"})[room.phase]||"야피아";
 $("center-subtitle").textContent=room.phase==="lobby"?`${room.players.length}/6명이 모였습니다`:room.phase==="night"?`${room.round}번째 밤 · 각자 비밀 행동`:room.phase==="ended"?"마지막 진실이 밝혀졌습니다":`${room.round}번째 라운드`;
 $("host-controls").classList.toggle("hidden",!state.isHost||room.phase==="ended");
 $("start-btn").classList.toggle("hidden",room.started||!state.isHost);
 $("start-btn").disabled=room.players.length!==6;
 $("start-btn").textContent=room.players.length===6?"게임 시작":"6명 입장 시 시작 가능 ("+room.players.length+"/6)";
 $("vote-start-btn").classList.toggle("hidden",room.phase!=="day"||!state.isHost);
 $("next-night-btn").classList.toggle("hidden",room.phase!=="day_result"||!state.isHost);
 $("vote-controls").classList.toggle("hidden",room.phase!=="vote"||!me()?.alive||state.voted);
 const targetList=aliveTargets(false);populateSelect($("vote-select"),targetList);
 if(state.role){
  $("role-empty").classList.add("hidden");$("role-content").classList.remove("hidden");
  $("role-symbol").textContent=roleSymbols[state.role.role]||"♟";$("role-name").textContent=state.role.role_label;
  $("role-person").textContent=state.role.role_name;$("role-description").textContent=state.role.description;
  $("mafia-tab").classList.toggle("hidden",state.role.role!=="mafia");
 }else{$("role-empty").classList.remove("hidden");$("role-content").classList.add("hidden");$("mafia-tab").classList.add("hidden")}
 renderActions();
 $("chat-hint").textContent=room.phase==="night"?(state.role?.role==="mafia"?"밤에는 마피아 비밀 채팅을 사용할 수 있습니다.":"밤에는 채팅할 수 없습니다."): "낮에는 생존자 전체 채팅을 사용할 수 있습니다.";
 if(room.phase==="ended")$("game-over").classList.remove("hidden");else $("game-over").classList.add("hidden");
}
function renderActions(){
 const p=me();const role=state.role?.role;
 const can=state.phase==="night"&&p?.alive&&["mafia","doctor","police"].includes(role)&&!state.submitted;
 $("role-actions").classList.toggle("hidden",!can);
 if(!can)return;
 $("target-label").textContent=role==="mafia"?"밤에 제거할 대상":role==="doctor"?"보호할 대상":"조사할 대상";
 const targets=aliveTargets(role==="doctor");populateSelect($("target-select"),targets);
 $("action-btn").textContent=role==="mafia"?"제거 대상 선택":role==="doctor"?"보호 대상 선택":"조사하기";
 $("action-note").textContent=state.submitted?"행동 제출 완료":role==="doctor"?"자기 자신도 보호할 수 있습니다.":"선택 결과는 다른 플레이어에게 공개되지 않습니다.";
}
function addChat(data){
 const log=$("chat-log");const ph=log.querySelector(".chat-placeholder");if(ph)ph.remove();
 const line=document.createElement("div");line.className="chat-line";
 if(data.system){line.classList.add("system");line.textContent=data.message}
 else{const n=document.createElement("span");n.className="chat-name";n.textContent=data.name;
 const m=document.createElement("span");m.textContent=data.message;line.append(n,m)}
 log.appendChild(line);log.scrollTop=log.scrollHeight;
}
function addSystem(message){addChat({system:true,message})}
function enterRoom(payload){state.code=payload.code;state.isHost=payload.is_host;state.pid=payload.pid;showGame();$("chat-log").innerHTML="";addSystem("방에 입장했습니다. 방 코드 "+payload.code+"를 친구에게 공유하세요.");}
$("create-btn").onclick=()=>{const name=$("nickname").value.trim();if(!name)return toast("닉네임을 입력해 주세요.");state.name=name;socket.emit("create_room",{name,token:state.token})};
$("join-btn").onclick=()=>{const name=$("nickname").value.trim(),code=$("room-code").value.trim().toUpperCase();if(!name)return toast("닉네임을 입력해 주세요.");if(!code)return toast("참가할 방 코드를 입력해 주세요.");state.name=name;socket.emit("join_room",{name,code,token:state.token})};
$("start-btn").onclick=()=>socket.emit("start_game");
$("vote-start-btn").onclick=()=>socket.emit("start_vote");
$("next-night-btn").onclick=()=>{state.submitted=false;state.voted=false;socket.emit("next_night")};
$("action-btn").onclick=()=>{const target=$("target-select").value;if(!target)return toast("대상을 선택해 주세요.");socket.emit("night_action",{target});state.submitted=true;renderActions()};
$("vote-btn").onclick=()=>{const target=$("vote-select").value;if(!target)return toast("투표 대상을 선택해 주세요.");socket.emit("cast_vote",{target});state.voted=true;$("vote-controls").classList.add("hidden")};
$("chat-form").onsubmit=e=>{e.preventDefault();const message=$("chat-input").value.trim();if(!message)return;socket.emit("chat_message",{message,channel:state.channel});$("chat-input").value=""};
document.querySelectorAll(".chat-tab").forEach(btn=>btn.onclick=()=>{state.channel=btn.dataset.channel;document.querySelectorAll(".chat-tab").forEach(b=>b.classList.toggle("active",b===btn));$("chat-input").placeholder=state.channel==="mafia"?"마피아에게만 보이는 메시지...":"메시지를 입력하세요..."});
$("copy-code").onclick=async()=>{try{await navigator.clipboard.writeText(state.code);toast("방 코드를 복사했습니다.")}catch(e){toast("방 코드: "+state.code)}};
$("back-lobby").onclick=()=>{location.reload()};
socket.on("joined_room",enterRoom);
socket.on("room_update",room=>{const oldPhase=state.phase;renderRoom(room);if(oldPhase!==room.phase){state.submitted=false;state.voted=false;renderActions()}});
socket.on("role_info",role=>{state.role=role;renderRoom(state.room||{players:[],phase:"lobby",code:state.code,host:state.token,round:0});addSystem("비공개 역할이 배정되었습니다.");});
socket.on("phase_update",data=>{state.phase=data.phase;state.submitted=false;state.voted=false;if(data.message)addSystem(data.message);if(state.room)renderRoom({...state.room,phase:data.phase,round:data.round,message:data.message});});
socket.on("system_message",data=>addSystem(data.message));
socket.on("chat_message",data=>addChat(data));
socket.on("action_ack",data=>toast(data.message));
socket.on("investigation_result",data=>{toast(data.message);addSystem("경찰 조사 결과: "+data.message)});
socket.on("game_over",data=>{state.phase="ended";$("winner-title").textContent=data.message;$("game-over").classList.remove("hidden");$("role-reveal").innerHTML="";data.roles.forEach(p=>{const row=document.createElement("div");row.className="revealed-role";const a=document.createElement("span"),b=document.createElement("span");a.textContent=p.name;b.textContent=p.role+" · "+p.role_name;row.append(a,b);$("role-reveal").appendChild(row)});addSystem(data.message)});
socket.on("error_message",data=>toast(data.message));
