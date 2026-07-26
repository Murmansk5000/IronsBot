FROM python:3.10 as requirements_stage

WORKDIR /wheel

RUN python -m pip install --user uv

COPY ./pyproject.toml \
  ./uv.lock \
  /wheel/

RUN python -m uv export --format requirements.txt --output-file requirements.txt --no-hashes

RUN python -m pip wheel --wheel-dir=/wheel --no-cache-dir --requirement ./requirements.txt

RUN python -c "\
import urllib.request, zipfile, io, os;\
os.makedirs('/tmp/fonts', exist_ok=True);\
url='https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip';\
data=urllib.request.urlopen(url).read();\
z=zipfile.ZipFile(io.BytesIO(data));\
[open(f'/tmp/fonts/{os.path.basename(n)}','wb').write(z.read(n)) for n in z.namelist() if n.endswith('.otf') and ('Regular' in n or 'Bold' in n)]"


FROM python:3.10-slim

WORKDIR /app

ENV TZ Asia/Shanghai
ENV PYTHONPATH=/app
# Emit Python stack traces to container logs when a native extension crashes.
ENV PYTHONFAULTHANDLER=1

COPY --from=requirements_stage /tmp/fonts/ /usr/share/fonts/opentype/source-han-sans/
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=requirements_stage /wheel /wheel

RUN pip install --no-cache-dir --no-index --find-links=/wheel -r /wheel/requirements.txt \
    && rm -rf /wheel
COPY . /app/

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["python", "-m", "ironsbot"]
