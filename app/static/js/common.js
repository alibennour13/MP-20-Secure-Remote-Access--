
const ROBOT_ID = "{{ robot.id }}";
let toastTimer = null;
function showToast(message, isError) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = "toast show" + (isError ? " toast-error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.className = "toast", 2600);
}
async function postJSON(url, data) {
    try {
        const payload = Object.assign({ robot_id: ROBOT_ID }, data || {});
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        showToast(result.message || (result.success ? "Termine" : "Action impossible"), !result.success);
        return result;
    } catch (e) {
        showToast("Connexion au robot impossible. Reessayez.", true);
        return { success: false };
    }
}
async function robotAction(url) {
    const r = await postJSON(url, {});
    if (r.success) setTimeout(() => location.reload(), 600);
}
