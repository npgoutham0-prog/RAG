(() => {
  const fileInput = document.getElementById("file-input");
  const chooseFiles = document.getElementById("choose-files");
  const crawlForm = document.getElementById("crawl-form");
  const crawlUrlInput = document.getElementById("crawl-url");
  const crawlButton = document.getElementById("crawl-button");
  const sourcesPanel = document.querySelector(".sources-panel");
  const documentList = document.getElementById("document-list");
  const sourceTotal = document.getElementById("source-total");
  const selectAll = document.getElementById("select-all");
  const selectedCount = document.getElementById("selected-count");
  const searchInput = document.getElementById("source-search");
  const form = document.getElementById("chat-form");
  const questionInput = document.getElementById("question-input");
  const sendButton = document.getElementById("send-button");
  const sendButtonAnchor = sendButton.closest(".send-button-anchor");
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

  function isNexusKnowledgeQuestion(question) {
    return /\bnexus\b/i.test(question)
      && /\b(build|built|builder|builders|create|created|creator|creators|develop|developed|developer|developers|founder|founders|founded|made|feature|features|capability|capabilities|technology|technologies|tech stack|framework|language|vision|goal|goals|purpose|rag|retrieval|what is|what's|who is|tell me about|describe|about)\b/i.test(question);
  }

  function isGreeting(question) {
    return /^(hi|hello)[!?.\s]*$/i.test(question.trim());
  }

  function isThankYou(question) {
    return /^(thank you|thanks|thank you so much|thanks so much)[!?.\s]*$/i.test(question.trim());
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
      const item = document.createElement("div");
      item.className = "document-item";
      item.dataset.name = documentRecord.name.toLowerCase();
      const choice = document.createElement("label");
      choice.className = "document-choice";
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
      choice.append(checkbox, icon, name, indicator);
      const deleteButton = document.createElement("button");
      deleteButton.className = "delete-document";
      deleteButton.type = "button";
      deleteButton.setAttribute("aria-label", `Delete ${documentRecord.name}`);
      deleteButton.title = "Delete source";
      deleteButton.textContent = "×";
      item.append(choice, deleteButton);
      documentList.append(item);
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
  async function uploadDirectFile(file) {
    const signedResponse = await fetch("/api/upload/presign/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ name: file.name, size: file.size }),
    });
    const signedUpload = await signedResponse.json();
    if (!signedResponse.ok) throw new Error(signedUpload.error || "Could not prepare the upload.");

    let storageResponse;
    try {
      storageResponse = await fetch(signedUpload.upload_url, {
        method: "PUT",
        headers: { "Content-Type": signedUpload.content_type },
        body: file,
      });
    } catch {
      throw new Error("Could not reach Supabase Storage. Check its CORS settings and try again.");
    }
    if (!storageResponse.ok) {
      throw new Error(`Supabase Storage rejected the upload (${storageResponse.status}).`);
    }

    const completeResponse = await fetch("/api/upload/complete/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ upload_token: signedUpload.upload_token }),
    });
    const result = await completeResponse.json();
    if (!completeResponse.ok) throw new Error(result.error || "Could not finish the upload.");
    return result;
  }

  async function uploadFiles(files) {
    if (!files.length) return;
    chooseFiles.disabled = true;
    chooseFiles.textContent = "Adding sources…";
    const uploadedDocuments = [];
    try {
      if (fileInput.dataset.directUpload === "true") {
        for (const file of files) uploadedDocuments.push(await uploadDirectFile(file));
      } else {
        const data = new FormData();
        [...files].forEach((file) => data.append("files", file));
        const response = await fetch("/api/upload/", {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body: data,
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Upload failed.");
        uploadedDocuments.push(...result.documents);
      }
      await refreshDocuments(new Set(uploadedDocuments.map((document) => String(document.id))));
      showToast(`${uploadedDocuments.length} ${uploadedDocuments.length === 1 ? "source added" : "sources added"}.`);
    } catch (error) {
      let message = error.message;
      if (uploadedDocuments.length) {
        message = `${uploadedDocuments.length} file(s) uploaded before an error. ${message}`;
        try {
          await refreshDocuments(new Set(uploadedDocuments.map((document) => String(document.id))));
        } catch (refreshError) {
          message += ` Sources could not be refreshed: ${refreshError.message}`;
        }
      }
      showToast(message, true);
    } finally {
      fileInput.value = "";
      chooseFiles.disabled = false;
      chooseFiles.innerHTML = '<span class="plus-icon">+</span> Add sources';
    }
  }
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
  crawlForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    crawlButton.disabled = true;
    crawlButton.textContent = "Crawling…";
    try {
      const response = await fetch("/api/crawl/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ url: crawlUrlInput.value.trim() }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not crawl this website.");
      const selected = new Set(selectedIds());
      selected.add(String(result.id));
      await refreshDocuments(selected);
      crawlUrlInput.value = "";
      showToast("Website added as a source.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      crawlButton.disabled = false;
      crawlButton.textContent = "Crawl URL";
    }
  });
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

  documentList.addEventListener("click", async (event) => {
    const button = event.target instanceof Element
      ? event.target.closest(".delete-document")
      : null;
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    if (!window.confirm("Delete this source? This cannot be undone.")) return;

    const item = button.closest(".document-item");
    button.disabled = true;
    try {
      const response = await fetch(`/api/documents/${item.querySelector(".document-check").value}/delete/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not delete this source.");

      item.remove();
      const remaining = documentList.querySelectorAll(".document-item").length;
      sourceTotal.textContent = String(remaining);
      if (!remaining) {
        const empty = document.createElement("div");
        empty.className = "empty-sources";
        empty.innerHTML = '<span class="empty-file-icon" aria-hidden="true">▤</span><strong>No sources yet</strong><span>Add a document to start asking questions.</span>';
        documentList.append(empty);
      }
      updateSelection();
      showToast("Source deleted.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  });

  sendButton.addEventListener("click", () => {
    sendButtonAnchor.classList.remove("is-launching");
    void sendButtonAnchor.offsetWidth;
    sendButtonAnchor.classList.add("is-launching");
  });
  sendButtonAnchor.addEventListener("animationend", (event) => {
    if (event.animationName === "send-button-jump") {
      sendButtonAnchor.classList.remove("is-launching");
    }
  });

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
    avatar.textContent = role === "user" ? "⌬" : error ? "!" : "✦";
    const body = document.createElement("div");
    body.className = "message-body";
    const author = document.createElement("div");
    author.className = "message-author";
    author.textContent = role === "user" ? "You" : error ? "Something went wrong" : "NEXUS";
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

  async function typeAssistantMessage(message, content) {
    const text = message.querySelector(".message-text");
    const textContent = document.createTextNode("");
    const characters = Array.from(content);
    const chunkSize = 3;
    text.classList.add("typing-cursor");
    text.append(textContent);
    for (let index = 0; index < characters.length; index += chunkSize) {
      textContent.appendData(characters.slice(index, index + chunkSize).join(""));
      chatHistory.scrollTop = chatHistory.scrollHeight;
      await new Promise((resolve) => window.setTimeout(resolve, 14));
    }
    text.classList.remove("typing-cursor");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    const documentIds = selectedIds();
    if (!question) return;
    if (!documentIds.length && !isGreeting(question) && !isThankYou(question) && !isNexusKnowledgeQuestion(question)) {
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
      const answer = appendMessage("assistant", "", result.sources);
      await typeAssistantMessage(answer, result.answer);
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
