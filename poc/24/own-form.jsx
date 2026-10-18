import React from 'react';
// minimal schema-driven form: text/password/number/boolean/enum/array-of-string
const label = (k, s) => s.title || k;
const field = (k, s, v, set) => {
  const common = { id: k, value: v ?? '', onChange: e => set(k, e.target.type === 'checkbox' ? e.target.checked : e.target.value) };
  if (s.type === 'boolean') return React.createElement('input', { ...common, type: 'checkbox', checked: !!v });
  if (s.enum) return React.createElement('select', common, s.enum.map(o => React.createElement('option', { key: o, value: o }, o)));
  const type = s.format === 'password' ? 'password' : s.type === 'number' || s.type === 'integer' ? 'number' : 'text';
  return React.createElement('input', { ...common, type, placeholder: s.description || '' });
};
export function SchemaForm({ schema, value, onChange }) {
  const [state, setState] = React.useState(value || {});
  const set = (k, v) => { const n = { ...state, [k]: v }; setState(n); onChange?.(n); };
  return React.createElement('form', { onSubmit: e => e.preventDefault() },
    Object.entries(schema.properties || {}).map(([k, s]) =>
      React.createElement('label', { key: k, style: { display: 'block', marginBottom: 8 } },
        React.createElement('span', null, label(k, s), s.required ? ' *' : ''),
        field(k, s, state[k], set))));
}
