// 通用脚本
document.addEventListener("DOMContentLoaded", function () {
  // chip 单选/多选样式同步
  document.querySelectorAll(".chips").forEach(function (group) {
    group.querySelectorAll(".chip input").forEach(function (input) {
      input.addEventListener("change", function () {
        if (input.type === "radio") {
          group.querySelectorAll(".chip").forEach(c => c.classList.remove("selected"));
          input.closest(".chip").classList.add("selected");
        } else {
          input.closest(".chip").classList.toggle("selected", input.checked);
        }
      });
      // 初始
      if (input.checked) input.closest(".chip").classList.add("selected");
    });
  });
});

// 记忆花园互动
function gardenAct(action, petName) {
  fetch("/garden/act", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: action, pet_name: petName }),
  })
    .then(r => r.json())
    .then(data => {
      document.getElementById("garden-feedback").innerText = data.text;
      const stats = window.__gardenStats || { happy: 60, company: 50, miss: 70 };
      stats.happy = Math.max(0, Math.min(100, stats.happy + (data.delta.happy || 0)));
      stats.company = Math.max(0, Math.min(100, stats.company + (data.delta.company || 0)));
      stats.miss = Math.max(0, Math.min(100, stats.miss + (data.delta.miss || 0)));
      window.__gardenStats = stats;
      document.getElementById("stat-happy").innerText = stats.happy;
      document.getElementById("stat-company").innerText = stats.company;
      document.getElementById("stat-miss").innerText = stats.miss;
    });
}

function gardenSay(petName) {
  const input = document.getElementById("say-input");
  const text = (input.value || "").trim();
  if (!text) { alert("写一句想说的话吧～"); return; }
  const wall = document.getElementById("wall");
  const msg = document.createElement("div");
  msg.className = "msg";
  msg.innerText = "你对 " + petName + " 说：" + text;
  wall.prepend(msg);
  input.value = "";
  gardenAct("say", petName);
}
