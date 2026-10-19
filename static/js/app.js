(() => {
  const fileInput = document.getElementById("file-input");
  const chooseFiles = document.getElementById("choose-files");
  const sourcesPanel = document.querySelector(".sources-panel");
  const documentList = document.getElementById("document-list");
  const sourceTotal = document.getElementById("source-total");
  const selectAll = document.getElementById("select-all");
  const selectedCount = document.getElementById("selected-count");
  const searchInput = document.getElementById("source-search");
  const form = document.getElementById("chat-form");
  const questionInput = document.getElementById("question-input");
  const sendButton = document.getElementById("send-button");
  const chatHistory = document.getElementById("chat-history");
  const welcome = document.getElementById("welcome");
  const toast = document.getElementById("toast");
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  let toastTimer;

  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.classList.toggle("toast-error", isError);
    toast.classList.add("visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 4200);
  }

  function selectedIds() {
    return [...document.querySelectorAll(".document-check:checked")].map((input) => input.value);
  }

  function updateSelection() {
    const checks = [...document.querySelectorAll(".document-check")];
    const selected = checks.filter((input) => input.checked).length;
    selectedCount.textContent = `${selected} ${selected === 1 ? "source" : "sources"} selected`;
    selectAll.checked = checks.length > 0 && selected === checks.length;
    selectAll.indeterminate = selected > 0 && selected < checks.length;
    checks.forEach((input) => input.closest(".document-item").classList.toggle("selected", input.checked));
  }

  function renderDocuments(documents, selected = new Set()) {
    documentList.replaceChildren();
    if (!documents.length) {
      const empty = document.createElement("div");
      empty.className = "empty-sources";
      empty.innerHTML = '<span class="empty-file-icon" aria-hidden="true">▤</span><strong>No sources yet</strong><span>Add a document to start asking questions.</span>';
      documentList.append(empty);
      sourceTotal.textContent = "0";
      updateSelection();
      return;
    }

    documents.forEach((documentRecord) => {
      const label = document.createElement("label");
      label.className = "document-item";
      label.dataset.name = documentRecord.name.toLowerCase();
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "document-check";
      checkbox.value = documentRecord.id;
      checkbox.checked = selected.size === 0 || selected.has(String(documentRecord.id));
      const icon = document.createElement("span");
      icon.className = `file-icon${documentRecord.name.toLowerCase().endsWith(".pdf") ? " pdf-icon" : ""}`;
      icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 2.75h8l4.5 4.5v14H6z"/><path d="M14 2.75v5h4.5M9 12h6M9 15h6M9 18h4"/></svg>';
      const name = document.createElement("span");
      name.className = "document-name";
      name.title = documentRecord.name;
      name.textContent = documentRecord.name;
      const indicator = document.createElement("span");
      indicator.className = "check-indicator";
      indicator.setAttribute("aria-hidden", "true");
      indicator.textContent = "✓";
      label.append(checkbox, icon, name, indicator);
      documentList.append(label);
    });
    sourceTotal.textContent = String(documents.length);
    updateSelection();
    applySearch();
  }

  function applySearch() {
    const query = searchInput.value.trim().toLowerCase();
    document.querySelectorAll(".document-item").forEach((item) => {
      item.classList.toggle("filtered-out", !item.dataset.name.includes(query));
    });
  }

  async function refreshDocuments(selected = new Set()) {
    const response = await fetch("/api/documents/");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load your sources.");
    renderDocuments(data.documents, selected);
  }

  chooseFiles.addEventListener("click", () => fileInput.click());
  async function uploadFiles(files) {
    if (!files.length) return;
    const data = new FormData();
    [...files].forEach((file) => data.append("files", file));
    chooseFiles.disabled = true;
    chooseFiles.textContent = "Adding sources…";
    try {
      const response = await fetch("/api/upload/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: data,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Upload failed.");
      await refreshDocuments(new Set(result.documents.map((document) => String(document.id))));
      showToast(`${result.documents.length} ${result.documents.length === 1 ? "source added" : "sources added"}.`);
    } catch (error) {
      showToast(error.message, true);
    } finally {
      fileInput.value = "";
      chooseFiles.disabled = false;
      chooseFiles.innerHTML = '<span class="plus-icon">+</span> Add sources';
    }
  }
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
  sourcesPanel.addEventListener("dragover", (event) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    sourcesPanel.classList.add("drop-target");
  });
  sourcesPanel.addEventListener("dragleave", (event) => {
    if (!sourcesPanel.contains(event.relatedTarget)) sourcesPanel.classList.remove("drop-target");
  });
  sourcesPanel.addEventListener("drop", (event) => {
    event.preventDefault();
    sourcesPanel.classList.remove("drop-target");
    uploadFiles(event.dataTransfer.files);
  });

  documentList.addEventListener("change", (event) => {
    if (event.target.matches(".document-check")) updateSelection();
  });
  selectAll.addEventListener("change", () => {
    document.querySelectorAll(".document-check").forEach((input) => {
      input.checked = selectAll.checked;
    });
    updateSelection();
  });
  searchInput.addEventListener("input", applySearch);

  document.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.question;
      questionInput.focus();
      questionInput.dispatchEvent(new Event("input"));
    });
  });

  function appendMessage(role, content, sources = [], error = false) {
    const article = document.createElement("article");
    article.className = `message message-${role}${error ? " message-error" : ""}`;
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "G" : error ? "!" : "✦";
    const body = document.createElement("div");
    body.className = "message-body";
    const author = document.createElement("div");
    author.className = "message-author";
    author.textContent = role === "user" ? "You" : error ? "Something went wrong" : "DocuChat";
    const text = document.createElement("div");
    text.className = "message-text";
    text.textContent = content;
    body.append(author, text);
    if (sources.length) {
      const sourceRow = document.createElement("div");
      sourceRow.className = "message-sources";
      sources.forEach((source) => {
        const chip = document.createElement("span");
        chip.className = "source-chip";
        chip.textContent = `▤ ${source}`;
        sourceRow.append(chip);
      });
      body.append(sourceRow);
    }
    article.append(avatar, body);
    chatHistory.append(article);
    welcome.hidden = true;
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return article;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    const documentIds = selectedIds();
    if (!question) return;
    if (!documentIds.length) {
      showToast("Select at least one source before asking a question.", true);
      return;
    }

    appendMessage("user", question);
    questionInput.value = "";
    questionInput.style.height = "31px";
    const pending = appendMessage("assistant", "Searching your sources…");
    pending.querySelector(".message-text").classList.add("typing-indicator");
    sendButton.disabled = true;
    try {
      const response = await fetch("/api/chat/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ question, document_ids: documentIds }),
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 422) {
          pending.remove();
          appendMessage("assistant", result.error || "No relevant information was found in the selected sources.");
          return;
        }
        throw new Error(result.error || "The question could not be answered.");
      }
      pending.remove();
      appendMessage("assistant", result.answer, result.sources);
    } catch (error) {
      pending.remove();
      appendMessage("assistant", error.message, [], true);
    } finally {
      sendButton.disabled = false;
      questionInput.focus();
    }
  });

  questionInput.addEventListener("input", () => {
    questionInput.style.height = "31px";
    questionInput.style.height = `${Math.min(questionInput.scrollHeight, 130)}px`;
  });
  questionInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  document.getElementById("clear-chat").addEventListener("click", () => {
    if (!window.confirm("Clear the saved conversation? This cannot be undone.")) return;
    fetch("/api/chat/clear/", {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken },
    }).then(async (response) => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not clear the conversation.");
      chatHistory.replaceChildren();
      welcome.hidden = false;
      showToast("Conversation cleared.");
    }).catch((error) => showToast(error.message, true));
  });

  updateSelection();
})();
