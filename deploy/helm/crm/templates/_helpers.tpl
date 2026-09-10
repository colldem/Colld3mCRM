{{- define "crm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "crm.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "crm.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "crm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "crm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "crm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "crm.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "crm.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "crm.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- define "crm.secretName" -}}
{{- .Values.existingSecret | default (printf "%s-secrets" (include "crm.fullname" .)) -}}
{{- end -}}

{{/*
Every container gets the same environment: plain settings from the ConfigMap,
credentials from the Secret. Migrations and static files are handled once per
release, never on pod start-up.
*/}}
{{- define "crm.env" -}}
- name: CRM_RUN_MIGRATIONS
  value: "0"
- name: CRM_COLLECTSTATIC
  value: "0"
- name: DB_HOST
  value: {{ required "database.host is required — the chart ships no database" .Values.database.host | quote }}
- name: DB_PORT
  value: {{ .Values.database.port | quote }}
- name: DB_NAME
  value: {{ .Values.database.name | quote }}
- name: DB_USER
  value: {{ .Values.database.user | quote }}
- name: CRM_GUNICORN_WORKERS
  value: {{ .Values.gunicorn.workers | quote }}
- name: CRM_GUNICORN_THREADS
  value: {{ .Values.gunicorn.threads | quote }}
- name: CRM_GUNICORN_TIMEOUT
  value: {{ .Values.gunicorn.timeout | quote }}
{{- end -}}

{{- define "crm.envFrom" -}}
- configMapRef:
    name: {{ include "crm.fullname" . }}-config
- secretRef:
    name: {{ include "crm.secretName" . }}
{{- end -}}

{{/* The host the ingress serves, reused for ALLOWED_HOSTS and CSRF. */}}
{{- define "crm.host" -}}
{{- .Values.ingress.host -}}
{{- end -}}
