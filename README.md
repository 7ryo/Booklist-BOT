# Booklist-BOT: A LangChain-powered Discord assistant for personalized library & reading management.
This project integrates **Public Library** metadata with **Notion** databases via **LangChain**, creating a workflow for personal book collection management.


## Motivation
While current library systems offer location filter for general searches, they often lack the ability to **filter within a user's "Favorites" or "Wishlist"**. When a user has a large curated list of books, it is unwieldly to manually check which ones are currently available at a **specific branch library**.

The BOT fills this gap by:
- **Location Filtering**: Instantly identify which books from a private favorites list are held by specific branches.


- **Knowledge Base Management**: By connecting to a Notion database, the user can create reading records including basic book details and reviews. 


- **Intelligent Recommendation**: User can ask the robot to recommend books by referencing the reviews in Notion and Google search (API).

## Technical Scope & Limitations
- **Target Users**: This tool is developed for personal use and private booklist management.
- **System Compatibility**: The current version of !lib is specifically optimized for the Kaohsiung Public Library system. It leverages specific parsing logic tailored to the library's book information, branch structure and availability data.
- **Data Privacy**: Both PosgreSQL and Notion intergrations are designed for private databases; credentials are managed strictly via environment variables.

## Command Structure
```
Booklist-BOT (Core Logic)
├── !lib            # Query metadata of books 
├── !note           # CRUD operations on Notion
└── !recommend      # RAG-based recommendations using Notion & Google Search
```

## Key Features
### Libraray Query (`!lib`)
Provide book metadata.
* To ensure stability and faster response times, book information is pre-fetched and managed in a structured database. This reduces direct requests to the library's website and prevents potential IP blocking.
* The bot retrieve keywords from user input and format them into a query string, to search for desire information in the structured database.
* Example: `!lib 請幫我找「人間失格」在哪個分館`



### Notion Assistant (`!note`)
Manages reading records within a Notion database using natural language.

* The bot analyzes user messages to determine whether to update an existing record's status and content, or to create a new entry.
* This helps keeping the user's personal reading list up-to-date without manual database entry.
* Example: `!note I've finished reading Brave New World`



### Intelligent Recommendation (`!recommend`)
Generate book suggestions based on personal references and Internet searches.
* Utilize the concept of RAG workflow, combining user reviews stored in Notion with external information from Google Search to provide context-aware recommendations.
* Example: `!recommend 請推薦我和「星期五的書店」相似的書`



## Tech Stack
- Language: Python 3.11 (Slim-image)
- Orchestration: LangChain
- LLM: Gemma3-4b-it
- Database: Notion API, Supabase (PostgreSQL)
- Infrastructure: Docker, Railway



## Challenges
Porblems to be solve / Future functions
1. **Hadling Hallucinations**: The recommendation function occasionally matches incorrect pairs of authors and books. **Refining system prompts** is required to ensure the AI provides factually accurate information. 

2. **Database Refreshing**: Explore methods to **automate library metadata synchronization** to unsure the favorites list and branch availabitiy are always up-to-date. 

3. **Support for Multiple Libraries**: Exapnd the parsing logic to support library systems beyond Kaohsiung Public Library.

4. **Multi-user**: Research secure methods for managing **individual environment variables (API keys)** of different users, and develop an **onbording tutorial** for settign up required database.

5. **24/7 Availability**: The bot was temporarily in **Railway** for testing. While the services is currently paused to manage costs, the long-term goal is to achieve **24/7 uptime** as a persistent Discord service.


