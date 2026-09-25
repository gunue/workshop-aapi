FROM registry.access.redhat.com/ubi9/python-312@sha256:6c4161d7da73fced103c8532ee6419510576f0b70bca4a18790878439973bc4d
USER 0
WORKDIR /opt/workshop
COPY --chown=0:0 app/server.py /opt/workshop/server.py
RUN chmod 0555 /opt/workshop && chmod 0444 /opt/workshop/server.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1001
EXPOSE 8080
ENTRYPOINT ["python3", "-B", "/opt/workshop/server.py"]
