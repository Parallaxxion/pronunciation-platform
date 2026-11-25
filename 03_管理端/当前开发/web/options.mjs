export function levelOptions(value = '', all = true) {
  const options = all ? ['<option value="">全部等级</option>'] : [];
  for (let level = 1; level <= 9; level++) {
    const selected = String(value) === String(level) ? ' selected' : '';
    options.push('<option value="' + level + '"' + selected + '>' + level + ' 级</option>');
  }
  return options.join('');
}
