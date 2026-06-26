{{/*
Backend environment, shared by the Deployment and the migrate Job.
*/}}
{{- define "ideabrd.backendEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
{{- if .Values.postgres.enabled }}
      name: {{ include "ideabrd.dbClusterName" . }}-app
      key: uri
{{- else }}
      name: {{ include "ideabrd.secretName" . }}
      key: DATABASE_URL
{{- end }}
- name: SESSION_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "ideabrd.secretName" . }}
      key: SESSION_SECRET
- name: GOOGLE_CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "ideabrd.secretName" . }}
      key: GOOGLE_CLIENT_ID
- name: GOOGLE_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "ideabrd.secretName" . }}
      key: GOOGLE_CLIENT_SECRET
- name: GITHUB_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "ideabrd.secretName" . }}
      key: GITHUB_TOKEN
- name: COOKIE_SECURE
  value: {{ .Values.config.cookieSecure | quote }}
- name: OAUTH_REDIRECT_URL
  value: {{ printf "%s/api/auth/callback" (include "ideabrd.publicUrl" .) | quote }}
- name: FRONTEND_URL
  value: {{ include "ideabrd.publicUrl" . | quote }}
{{- end -}}
