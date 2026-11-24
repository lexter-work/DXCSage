FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
COPY src ./src
# SAP NW RFC SDK and a pyrfc wheel are supplied by you in vendor/ (licensed, not in git).
# pyrfc is yanked on PyPI ("no longer supported"), so it is installed from your own wheel, not from pyproject.
COPY vendor /opt/vendor
RUN uv pip install --system --no-cache . \
 && (ls /opt/vendor/*.whl >/dev/null 2>&1 && uv pip install --system /opt/vendor/*.whl || echo "pyrfc wheel not provided: SAP calls will fail until it is added")
ENV SAPNWRFC_HOME=/opt/vendor/nwrfcsdk LD_LIBRARY_PATH=/opt/vendor/nwrfcsdk/lib SAGE_DATA_DIR=/data SAGE_KEY_DIR=/keys
EXPOSE 29700
CMD ["uvicorn", "sage.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "29700"]
