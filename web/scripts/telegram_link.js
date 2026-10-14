// ShelfLife: linking the account to the Telegram bot from the profile page.

function createTelegramLink() {
  const button = document.querySelector("#telegram-link-button");
  button.disabled = true;

  fetch("endpoints/telegram/link_token.php", {
    method: "POST",
    headers: { "X-CSRF-Token": window.csrfToken },
  })
    .then((response) => response.json())
    .then((data) => {
      if (!data.success) {
        showErrorMessage(data.message || translate("unknown_error"));
        return;
      }

      const url = document.querySelector("#telegram-link-url");
      url.href = data.link;
      url.textContent = data.link;
      document.querySelector("#telegram-link-command").textContent = "/start " + data.token;

      const qrCode = document.querySelector("#telegram-link-qr");
      qrCode.innerHTML = "";
      new QRCode(qrCode, data.link);

      document.querySelector("#telegram-link-result").classList.remove("hide");
    })
    .catch(() => showErrorMessage(translate("unknown_error")))
    .finally(() => {
      button.disabled = false;
    });
}

function unlinkTelegram() {
  fetch("endpoints/telegram/unlink.php", {
    method: "POST",
    headers: { "X-CSRF-Token": window.csrfToken },
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        window.location.reload();
      } else {
        showErrorMessage(data.message || translate("unknown_error"));
      }
    })
    .catch(() => showErrorMessage(translate("unknown_error")));
}
