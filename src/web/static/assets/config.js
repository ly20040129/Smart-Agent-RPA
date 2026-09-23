// /* ============================================================
//  * 配置 & 模板中心模块 (config.js)
//  *   负责: 我的配置加载/保存/上传、模板中心
//  * ============================================================ */

// function openConfigModal() {
//     fetch(API + '/api/my-config', {headers: authHeaders()})
//         .then(function(res){ return res.json(); })
//         .then(function(data) {
//             renderConfigForm(data.groups || []);
//             document.getElementById('config-modal').style.display = 'block';
//             document.getElementById('config-modal-overlay').style.display = 'block';
//         })
//         .catch(function(e){ addLog('加载配置失败: ' + e.message, 'error'); });
// }
// function closeConfigModal() {
//     document.getElementById('config-modal').style.display = 'none';
//     document.getElementById('config-modal-overlay').style.display = 'none';
// }

// function renderConfigForm(groups) {
//     var form = document.getElementById('config-form');
//     form.innerHTML = '';
//     for (var gi = 0; gi < groups.length; gi++) {
//         var g = groups[gi];
//         var groupDiv = document.createElement('div');
//         groupDiv.style.marginBottom = '20px';

//         var groupTitle = document.createElement('h3');
//         groupTitle.style.cssText = 'color:#008b8b;font-size:14px;margin-bottom:10px;border-bottom:1px solid #eee;padding-bottom:5px;';
//         groupTitle.textContent = g.label || g.name;
//         groupDiv.appendChild(groupTitle);

//         for (var ii = 0; ii < g.items.length; ii++) {
//             (function(item) {
//                 var itemDiv = document.createElement('div');
//                 itemDiv.style.cssText = 'margin-bottom:12px;padding:10px;background:#f8f9fa;border-radius:6px;';

//                 var label = document.createElement('label');
//                 label.style.cssText = 'display:block;font-weight:500;color:#555;font-size:13px;margin-bottom:4px;';
//                 var requiredMark = item.required ? ' <span style="color:#e74c3c;">*</span>' : '';
//                 label.innerHTML = item.label + requiredMark;
//                 itemDiv.appendChild(label);

//                 if (item.help) {
//                     var help = document.createElement('p');
//                     help.style.cssText = 'color:#999;font-size:11px;margin:2px 0 6px;';
//                     help.textContent = item.help;
//                     itemDiv.appendChild(help);
//                 }

//                 var inputRow = document.createElement('div');
//                 inputRow.style.cssText = 'display:flex;gap:8px;align-items:center;';

//                 var input = document.createElement('input');
//                 input.type = 'text';
//                 input.id = 'config-' + item.key.replace(/\./g, '-');
//                 input.placeholder = item.type === 'file' ? '可上传文件或直接填路径' : '请输入路径';
//                 input.value = item.current_value || '';
//                 input.style.cssText = 'flex:1;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;';
//                 input.setAttribute('data-key', item.key);
//                 inputRow.appendChild(input);

//                 if (item.type === 'file') {
//                     var uploadBtn = document.createElement('button');
//                     uploadBtn.className = 'btn btn-sm';
//                     uploadBtn.textContent = '📤 上传';
//                     uploadBtn.style.cssText = 'white-space:nowrap;';
//                     uploadBtn.onclick = function() { uploadConfigFile(item.key); };
//                     inputRow.appendChild(uploadBtn);

//                     if (item.is_uploaded) {
//                         var badge = document.createElement('span');
//                         badge.style.cssText = 'color:#27ae60;font-size:11px;white-space:nowrap;';
//                         badge.textContent = '✓ 已上传';
//                         inputRow.appendChild(badge);
//                     }
//                 }

//                 itemDiv.appendChild(inputRow);
//                 groupDiv.appendChild(itemDiv);
//             })(g.items[ii]);
//         }
//         form.appendChild(groupDiv);
//     }
// }

// function uploadConfigFile(key) {
//     var fileInput = document.createElement('input');
//     fileInput.type = 'file';
//     fileInput.style.display = 'none';
//     if (key.indexOf('template') >= 0 || key.indexOf('config_json') >= 0) {
//         fileInput.accept = '.xlsx,.xls,.json';
//     }
//     fileInput.onchange = async function() {
//         if (!fileInput.files.length) return;
//         var file = fileInput.files[0];
//         var formData = new FormData();
//         formData.append('key', key);
//         formData.append('file', file);
//         try {
//             addLog('上传文件: ' + file.name + ' ...', 'info');
//             var res = await fetch(API + '/api/my-config/upload', {
//                 method: 'POST',
//                 headers: {'Authorization': 'Bearer ' + token},
//                 body: formData,
//             });
//             var data = await res.json();
//             if (data.status === 'success') {
//                 var inputId = 'config-' + key.replace(/\./g, '-');
//                 var inputEl = document.getElementById(inputId);
//                 if (inputEl) inputEl.value = data.path;
//                 addLog('文件已上传: ' + data.filename, 'success');
//             } else {
//                 addLog('上传失败: ' + (data.detail || ''), 'error');
//             }
//         } catch(e) { addLog('上传失败: ' + e.message, 'error'); }
//     };
//     document.body.appendChild(fileInput);
//     fileInput.click();
//     document.body.removeChild(fileInput);
// }

// async function saveMyConfig() {
//     var inputs = document.querySelectorAll('#config-form input[data-key]');
//     var items = {};
//     for (var i = 0; i < inputs.length; i++) {
//         items[inputs[i].getAttribute('data-key')] = inputs[i].value;
//     }
//     var delivery = {
//         download_root: document.getElementById('config-download-root').value,
//         filename_pattern: document.getElementById('config-filename-pattern').value,
//         dingtalk_webhook: document.getElementById('config-dingtalk-webhook').value,
//         email_settings: {
//             smtp_server: document.getElementById('config-email-smtp').value,
//             smtp_port: document.getElementById('config-email-port').value,
//             sender: document.getElementById('config-email-sender').value,
//             password: document.getElementById('config-email-password').value,
//             receivers: document.getElementById('config-email-receivers').value
//         }
//     };
//     try {
//         var res = await fetch(API + '/api/my-config', {
//             method: 'POST',
//             headers: authHeaders(),
//             body: JSON.stringify({items: items, delivery: delivery}),
//         });
//         var data = await res.json();
//         if (data.status === 'success') {
//             addLog('配置已保存 (' + data.saved + '项)', 'success');
//             closeConfigModal();
//         } else {
//             addLog('保存失败', 'error');
//         }
//     } catch(e) { addLog('保存失败: ' + e.message, 'error'); }
// }

// function browseDownloadRoot() {
//     alert('请直接在输入框中填写路径，如：D:\\Downloads\\SmartAgent');
// }

// /* ---------- 模板中心 ---------- */
// function openTemplateModal() {
//     document.getElementById('template-modal').style.display = 'block';
//     document.getElementById('template-modal-overlay').style.display = 'block';
//     loadTemplates();
// }
// function closeTemplateModal() {
//     document.getElementById('template-modal').style.display = 'none';
//     document.getElementById('template-modal-overlay').style.display = 'none';
// }

// async function loadTemplates() {
//     var listEl = document.getElementById('template-list');
//     listEl.innerHTML = '<p style="color:#999;text-align:center;padding:20px;">加载中...</p>';
//     try {
//         var res = await fetch(API + '/api/templates', {headers: authHeaders()});
//         var data = await res.json();
//         var templates = data.templates || [];
//         if (!templates.length) {
//             listEl.innerHTML = '<p style="color:#999;text-align:center;padding:20px;">暂无模板，上传一个吧</p>';
//             return;
//         }
//         listEl.innerHTML = '';
//         for (var i = 0; i < templates.length; i++) {
//             (function(t) {
//                 var item = document.createElement('div');
//                 item.className = 'template-item';
//                 item.innerHTML = '<div class="template-info">' +
//                     '<div class="template-name">' + (t.name || '未命名') + '</div>' +
//                     '<div class="template-meta">' +
//                         (t.description || '') +
//                         (t.type ? ' · ' + t.type : '') +
//                         (t.upload_time ? ' · ' + t.upload_time : '') +
//                     '</div>' +
//                 '</div>';
//                 var actionsDiv = document.createElement('div');
//                 var delBtn = document.createElement('button');
//                 delBtn.className = 'btn btn-sm btn-danger';
//                 delBtn.textContent = '删除';
//                 delBtn.onclick = function() { deleteTemplate(t.id); };
//                 actionsDiv.appendChild(delBtn);
//                 item.appendChild(actionsDiv);
//                 listEl.appendChild(item);
//             })(templates[i]);
//         }
//     } catch(e) {
//         listEl.innerHTML = '<p style="color:#e74c3c;text-align:center;padding:20px;">加载失败: ' + e.message + '</p>';
//     }
// }

// async function uploadTemplate() {
//     var name = document.getElementById('tpl-name').value.trim();
//     var desc = document.getElementById('tpl-desc').value.trim();
//     var type = document.getElementById('tpl-type').value;
//     var fileInput = document.getElementById('tpl-file');
//     if (!name) { alert('请输入模板名称'); return; }
//     if (!fileInput.files.length) { alert('请选择文件'); return; }
//     var file = fileInput.files[0];
//     var formData = new FormData();
//     formData.append('name', name);
//     formData.append('description', desc);
//     formData.append('type', type);
//     formData.append('file', file);
//     try {
//         addLog('上传模板: ' + file.name + ' ...', 'info');
//         var res = await fetch(API + '/api/templates/upload', {
//             method: 'POST',
//             headers: {'Authorization': 'Bearer ' + token},
//             body: formData
//         });
//         var data = await res.json();
//         if (data.status === 'success') {
//             addLog('模板已上传: ' + name, 'success');
//             document.getElementById('tpl-name').value = '';
//             document.getElementById('tpl-desc').value = '';
//             document.getElementById('tpl-file').value = '';
//             loadTemplates();
//         } else {
//             addLog('上传失败: ' + (data.detail || ''), 'error');
//         }
//     } catch(e) { addLog('上传失败: ' + e.message, 'error'); }
// }

// async function deleteTemplate(id) {
//     if (!confirm('确定删除此模板？')) return;
//     try {
//         var res = await fetch(API + '/api/templates/' + id, {method: 'DELETE', headers: authHeaders()});
//         var data = await res.json();
//         if (data.status === 'success') {
//             addLog('模板已删除', 'success');
//             loadTemplates();
//         } else {
//             addLog('删除失败', 'error');
//         }
//     } catch(e) { addLog('删除失败: ' + e.message, 'error'); }
// }
