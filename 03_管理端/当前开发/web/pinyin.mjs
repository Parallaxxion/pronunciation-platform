// Display only. Keep the upstream numbered pinyin unchanged in stored data.
export function displayPinyin(value) {
  const original = String(value ?? '');
  const match = original.toLowerCase().match(/^([a-zü:]+)([0-5])$/u);
  if (!match) return original;
  const word = match[1].replace(/u:|v/g, 'ü');
  const tone = Number(match[2]);
  if (tone === 0 || tone === 5) return word;
  const vowels = [...word].map((c, i) => /[aeiouü]/u.test(c) ? i : -1).filter(i => i >= 0);
  let pos = word.indexOf('a');
  if (pos < 0) pos = word.indexOf('e');
  if (pos < 0 && word.includes('ou')) pos = word.indexOf('o');
  if (pos < 0) pos = vowels.at(-1) ?? -1;
  if (pos < 0) return original;
  const marked = {a:'āáǎà', e:'ēéěè', i:'īíǐì', o:'ōóǒò', u:'ūúǔù', ü:'ǖǘǚǜ'};
  return word.slice(0, pos) + marked[word[pos]][tone-1] + word.slice(pos+1);
}
