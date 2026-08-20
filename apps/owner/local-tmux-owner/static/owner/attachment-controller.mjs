export function isImageFile(file) {
  return /^image\//i.test(file?.type || "")
    || /\.(jpe?g|png|webp|gif|heic|heif)$/i.test(file?.name || "");
}

export function attachmentLabel(file) {
  const match = String(file?.name || "").match(/\.([^.]{1,5})$/);
  return match ? match[1].toUpperCase() : "FILE";
}

export function jpegName(name) {
  return `${(String(name || "image").replace(/\.[^.]*$/, "") || "image")}.jpg`;
}

export function selectedAttachmentFiles(files, currentCount, maximum) {
  return Array.from(files || []).slice(0, Math.max(0, maximum - currentCount));
}

export async function settleWithConcurrency(values, maximum, worker) {
  const items = Array.from(values || []);
  const limit = Math.max(1, Math.min(items.length || 1, Number(maximum) || 1));
  const results = new Array(items.length);
  let nextIndex = 0;
  async function run() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      try {
        results[index] = { status: "fulfilled", value: await worker(items[index], index) };
      } catch (reason) {
        results[index] = { status: "rejected", reason };
      }
    }
  }
  await Promise.all(Array.from({ length: limit }, () => run()));
  return results;
}

export function createAttachmentController(options = {}) {
  const view = options.view || globalThis;
  const document = options.document || view.document;
  const items = options.items || [];
  const preview = options.preview;
  const input = options.input;
  const trigger = options.trigger;
  const promptInput = options.promptInput;
  const maximum = Number(options.maximum || 35);
  const uploadConcurrency = Number(options.uploadConcurrency || 4);
  const imageMaxEdge = Number(options.imageMaxEdge || 1280);
  const imageQuality = Number(options.imageQuality || 0.6);
  const routeBase = String(options.routeBase || "");
  const URLApi = options.URL || view.URL;
  const ImageType = options.Image || view.Image;
  const FormDataType = options.FormData || view.FormData;
  const XMLHttpRequestType = options.XMLHttpRequest || view.XMLHttpRequest;
  if (!document || !preview || !input || !trigger || !promptInput) {
    throw new TypeError("Attachment controller requires document, preview, input, trigger, and promptInput");
  }

  function changed() {
    options.onChange?.(items);
  }

  function render() {
    const previousScrollLeft = Number(preview.scrollLeft || 0);
    const wasNearEnd = preview.scrollWidth - previousScrollLeft - preview.clientWidth < 8;
    preview.textContent = "";
    preview.classList.toggle("hidden", items.length === 0);
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `attachment-thumb ${item.kind === "file" ? "file" : ""} ${item.status || ""}`.trim();
      button.style.setProperty("--pct", item.progress || 0);
      button.title = ["compressing", "uploading"].includes(item.status)
        ? "Tap to cancel upload"
        : "Tap to remove";
      if (item.url) {
        const image = document.createElement("img");
        image.alt = "Uploaded image thumbnail";
        image.src = item.url;
        button.appendChild(image);
      } else {
        const label = document.createElement("span");
        label.className = "file-label";
        label.textContent = item.label || "FILE";
        button.appendChild(label);
      }
      if (["compressing", "uploading"].includes(item.status)) {
        const progress = document.createElement("span");
        progress.className = "upload-pct";
        progress.textContent = item.status === "compressing"
          ? "Prep"
          : (Number.isFinite(item.progress) ? `${item.progress}%` : "...");
        button.appendChild(progress);
      }
      const removeIcon = document.createElement("span");
      removeIcon.className = "upload-x";
      removeIcon.textContent = "×";
      button.appendChild(removeIcon);
      button.addEventListener("click", () => remove(item));
      preview.appendChild(button);
    }
    preview.scrollLeft = wasNearEnd ? preview.scrollWidth : previousScrollLeft;
    changed();
  }

  function remove(item) {
    if (item.xhr && item.status === "uploading") item.xhr.abort();
    if (item.url) URLApi.revokeObjectURL(item.url);
    const index = items.indexOf(item);
    if (index >= 0) items.splice(index, 1);
    render();
  }

  function clearSubmitted(paths) {
    const submitted = new Set((paths || []).filter(Boolean));
    if (!submitted.size) return;
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index];
      if (!submitted.has(item.path)) continue;
      if (item.url) URLApi.revokeObjectURL(item.url);
      items.splice(index, 1);
    }
    render();
  }

  function loadImage(file) {
    return new Promise((resolve, reject) => {
      const url = URLApi.createObjectURL(file);
      const image = new ImageType();
      image.onload = () => { URLApi.revokeObjectURL(url); resolve(image); };
      image.onerror = () => { URLApi.revokeObjectURL(url); reject(new Error("Image could not be read")); };
      image.src = url;
    });
  }

  async function compressImage(file) {
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type || "")) {
      return { blob: file, name: file.name || "image" };
    }
    try {
      const image = await loadImage(file);
      const width = image.naturalWidth || image.width;
      const height = image.naturalHeight || image.height;
      const scale = Math.min(1, imageMaxEdge / Math.max(width, height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", imageQuality));
      return blob && blob.size < file.size
        ? { blob, name: jpegName(file.name) }
        : { blob: file, name: file.name || "image" };
    } catch (_error) {
      return { blob: file, name: file.name || "image" };
    }
  }

  async function uploadItem(item) {
    item.status = item.kind === "image" ? "compressing" : "uploading";
    item.progress = item.kind === "image" ? 0 : 1;
    render();
    const upload = item.kind === "image"
      ? await compressImage(item.file)
      : { blob: item.file, name: item.file.name || "attachment" };
    if (!items.includes(item)) {
      const error = new Error("Upload canceled");
      error.canceled = true;
      throw error;
    }
    item.status = "uploading";
    item.progress = Math.max(1, item.progress || 1);
    render();
    const csrfHeaders = await options.csrfHeaders();
    return new Promise((resolve, reject) => {
      const form = new FormDataType();
      form.append("file", upload.blob, upload.name);
      const xhr = new XMLHttpRequestType();
      item.xhr = xhr;
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        item.progress = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
        render();
      };
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText || "{}"); } catch (_error) {}
        if (xhr.status >= 200 && xhr.status < 300 && data && data.ok !== false) resolve(data);
        else reject(new Error((data && data.error) || `Upload failed ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.onabort = () => {
        const error = new Error("Upload canceled");
        error.canceled = true;
        reject(error);
      };
      xhr.open("POST", `${routeBase}/api/attachment`);
      for (const [name, value] of Object.entries(options.ownerHeaders())) xhr.setRequestHeader(name, value);
      for (const [name, value] of Object.entries(csrfHeaders)) xhr.setRequestHeader(name, value);
      xhr.send(form);
    });
  }

  async function upload(files) {
    const selected = selectedAttachmentFiles(files, items.length, maximum);
    if (!selected.length) {
      input.value = "";
      if (items.length >= maximum) options.setError(`Attach up to ${maximum} files`);
      return;
    }
    const nextItems = selected.map((file) => {
      const kind = isImageFile(file) ? "image" : "file";
      return {
        file,
        kind,
        label: attachmentLabel(file),
        url: kind === "image" ? URLApi.createObjectURL(file) : "",
        status: kind === "image" ? "compressing" : "uploading",
        progress: 0,
      };
    });
    items.push(...nextItems);
    render();
    options.setBusy(true);
    options.setError("");
    try {
      await settleWithConcurrency(nextItems, uploadConcurrency, async (item) => {
        try {
          const data = await uploadItem(item);
          if (!items.includes(item)) return;
          item.path = data.path;
          item.kind = data.kind || item.kind;
          item.progress = 100;
          item.status = "ready";
        } catch (error) {
          if (error.canceled || !items.includes(item)) return;
          item.status = "error";
          options.setError(options.userErrorMessage(error));
        } finally {
          item.xhr = null;
          render();
        }
      });
      if (Array.from(files || []).length > selected.length) {
        options.setError(`Attach up to ${maximum} files`);
      }
    } finally {
      input.value = "";
      options.setBusy(false);
    }
  }

  function paste(event) {
    const clipboard = options.clipboardImageApi || {};
    const images = typeof clipboard.filesFromClipboard === "function"
      ? clipboard.filesFromClipboard(event.clipboardData)
      : [];
    if (!images.length) return;
    event.preventDefault();
    const pastedText = typeof clipboard.plainTextFromClipboard === "function"
      ? clipboard.plainTextFromClipboard(event.clipboardData)
      : "";
    if (pastedText && typeof clipboard.insertText === "function") {
      const inserted = clipboard.insertText(
        promptInput.value,
        promptInput.selectionStart,
        promptInput.selectionEnd,
        pastedText,
      );
      promptInput.value = inserted.value;
      promptInput.setSelectionRange(inserted.selectionStart, inserted.selectionStart);
      promptInput.dispatchEvent(new view.Event("input", { bubbles: true }));
    }
    options.closeDockMenu();
    upload(images).catch((error) => options.setError(options.userErrorMessage(error)));
  }

  function hasDraggedFiles(event) {
    return event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files");
  }

  function dragover(event) {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function drop(event) {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    upload(event.dataTransfer?.files).catch((error) => options.setError(options.userErrorMessage(error)));
  }

  function connect() {
    trigger.addEventListener("click", () => {
      if (items.length >= maximum) {
        options.setError(`Attach up to ${maximum} files`);
        return;
      }
      options.closeDockMenu();
      input.click();
    });
    input.addEventListener("change", () => {
      upload(input.files).catch((error) => options.setError(options.userErrorMessage(error)));
    });
    promptInput.addEventListener("paste", paste);
    document.addEventListener("dragover", dragover, true);
    document.addEventListener("drop", drop, true);
    render();
  }

  return { items, connect, render, remove, clearSubmitted, upload };
}
