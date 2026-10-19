import os

os.environ.setdefault("USER_AGENT", "rag-question-answering/1.0")

from langchain_community.document_loaders import WebBaseLoader
from langchain_community.vectorstores import SKLearnVectorStore
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from langchain_text_splitters import RecursiveCharacterTextSplitter


urls = [
    "https://lilianweng.github.io/posts/2023-06-23-agent/",
    "https://lilianweng.github.io/posts/2023-03-15-prompt-engineering/",
    "https://lilianweng.github.io/posts/2023-10-25-adv-attack-llm/",
]

docs = [
    document
    for url in urls
    for document in WebBaseLoader(url, raise_for_status=True).load()
]

text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    chunk_size=250,
    chunk_overlap=0,
)
doc_splits = text_splitter.split_documents(docs)
if not doc_splits:
    raise RuntimeError("No document content was loaded from the configured URLs.")

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)
vectorstore = SKLearnVectorStore.from_documents(
    documents=doc_splits,
    embedding=embeddings,
)
retriever = vectorstore.as_retriever(
    search_kwargs={"k": min(4, len(doc_splits))}
)

prompt = PromptTemplate(
    template="""You are an assistant for question-answering tasks.
Use the following documents to answer the question.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.
Question: {question}
Documents: {documents}
Answer:""",
    input_variables=["question", "documents"],
)

llm = ChatOllama(
    model="llama3.1",
    temperature=0,
    num_gpu=0,
)
rag_chain = prompt | llm | StrOutputParser()

print("Starting the question-answering loop. Type 'exit' to quit.")
while True:
    question = input("Question: ").strip()
    if question.lower() in {"exit", "quit"}:
        break
    if not question:
        continue

    relevant_docs = retriever.invoke(question)
    context = "\n\n".join(document.page_content for document in relevant_docs)
    answer = rag_chain.invoke({"question": question, "documents": context})
    print(f"\nAnswer: {answer}\n")