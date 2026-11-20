import React from 'react';
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
export function RjsfForm({ schema, value, onChange }) {
  return React.createElement(Form, { schema, validator, formData: value, onChange: e => onChange?.(e.formData), liveValidate: false });
}
