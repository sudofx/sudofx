(() => {
  const appendInline = (parent, text) => {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > cursor) parent.append(document.createTextNode(text.slice(cursor, match.index)));
      const token = match[0];
      if (token.startsWith('**')) {
        const strong = document.createElement('strong');
        strong.textContent = token.slice(2, -2);
        parent.append(strong);
      } else if (token.startsWith('`')) {
        const code = document.createElement('code');
        code.textContent = token.slice(1, -1);
        parent.append(code);
      } else {
        const parsed = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
        const link = document.createElement('a');
        link.textContent = parsed[1];
        link.href = parsed[2];
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        parent.append(link);
      }
      cursor = match.index + token.length;
    }
    if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
  };

  const render = text => {
    const container = document.createElement('div');
    container.className = 'conversation-markdown';
    const lines = String(text).replace(/\r\n/g, '\n').split('\n');
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (line.startsWith('```')) {
        const language = line.slice(3).trim();
        const codeLines = [];
        index++;
        while (index < lines.length && !lines[index].startsWith('```')) {
          codeLines.push(lines[index]);
          index++;
        }
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        if (language) code.dataset.language = language;
        code.textContent = codeLines.join('\n');
        pre.append(code);
        container.append(pre);
      } else if (/^#{1,3}\s+/.test(line)) {
        const level = Math.min(3, line.match(/^#+/)[0].length);
        const heading = document.createElement('h' + level);
        appendInline(heading, line.replace(/^#{1,3}\s+/, ''));
        container.append(heading);
      } else if (/^[-*]\s+/.test(line)) {
        const list = document.createElement('ul');
        while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
          const item = document.createElement('li');
          appendInline(item, lines[index].replace(/^[-*]\s+/, ''));
          list.append(item);
          index++;
        }
        container.append(list);
        continue;
      } else if (/^\d+\.\s+/.test(line)) {
        const list = document.createElement('ol');
        while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
          const item = document.createElement('li');
          appendInline(item, lines[index].replace(/^\d+\.\s+/, ''));
          list.append(item);
          index++;
        }
        container.append(list);
        continue;
      } else if (/^>\s?/.test(line)) {
        const quote = document.createElement('blockquote');
        appendInline(quote, line.replace(/^>\s?/, ''));
        container.append(quote);
      } else if (line.trim()) {
        const paragraph = document.createElement('p');
        appendInline(paragraph, line);
        container.append(paragraph);
      }
      index++;
    }
    return container;
  };

  const toDocument = transcript => {
    const sections = transcript.map(item => {
      const speaker = item.role === 'human' ? 'You' : 'Assistant';
      // Export the displayed transcript's UTC instant without creating a store.
      const stamp = item.timestamp ? ' · ' + item.timestamp : '';
      return '## ' + speaker + stamp + '\n\n' + String(item.text).trim();
    });
    return '# sudofx Conversation\n\n' + sections.join('\n\n---\n\n') + '\n';
  };

  window.SudofxConversationMarkdown = { render, toDocument };
})();
